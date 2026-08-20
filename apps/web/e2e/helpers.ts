import { readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn } from 'node:child_process'
import { expect, type Locator, type Page } from '@playwright/test'

// Not a *.spec.ts file on purpose: Playwright's own test-file glob
// (testDir: './e2e' in playwright.config.ts) only ever picks up *.spec.ts, so this
// module is safe to import from every spec here without becoming a "suite" of its
// own with zero tests in it.

export const ADMIN_EMAIL = 'e2e@pigro.it'
export const ADMIN_PASSWORD = 'supersegreta1'

export async function login(page: Page, email: string, password: string): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Accedi' }).click()
  await expect(page).toHaveURL(/\/app/)
}

export async function loginAsAdmin(page: Page): Promise<void> {
  await login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
}

/**
 * Types into the Kanban's "Nuovo campo"/customer-form "Etichetta" control one
 * keystroke at a time, the same way `FieldsPanel.test.tsx`'s own
 * `userEvent.type` does and `.fill()` cannot: seeing this as a defect at all
 * requires an event per character, because the bug it exists to catch
 * (task-10-brief.md, and this suite's own README-equivalent in
 * task-10-report.md) only manifests when the label's onChange handler runs once
 * per character instead of once for the whole string. A small inter-keystroke
 * delay, not the library's instant default, is deliberate: it is what a human
 * typing at a keyboard actually produces, and it is the exact gap `.fill()`'s
 * single synthetic event cannot represent at all.
 */
export async function typeLikeAHuman(locator: Locator, text: string): Promise<void> {
  await locator.pressSequentially(text, { delay: 20 })
}

/**
 * Drags a Kanban card (identified by its exact visible name) onto the column
 * whose header reads `stageName`, mirroring dnd-kit's own PointerSensor
 * (KanbanBoard.tsx: `activationConstraint: { distance: 6 }`) with a real
 * mouse-event sequence -- hover, `mousedown`, an intermediate move (so the drag
 * actually *activates* past the 6px threshold before the final jump, rather than
 * risking a single teleport dnd-kit's sensor could read as never having moved),
 * hover the target, `mouseup`.
 *
 * The column is found by its heading text and then narrowed to the *droppable*
 * child specifically (the element `useDroppable`'s own `setNodeRef` is attached
 * to, `KanbanBoard.tsx`'s `border-dashed` div) -- not the whole column wrapper,
 * which also contains the header/count/total and would let `.hover()`'s
 * bounding-box centre land outside the actual drop target on a short column.
 */
export async function dragDealToStage(page: Page, dealName: string, stageName: string): Promise<void> {
  const card = page.getByText(dealName, { exact: true })
  const column = page
    .locator('div.flex.w-72.shrink-0.flex-col')
    .filter({ has: page.getByRole('heading', { name: stageName, exact: true }) })
  const dropZone = column.locator('.border-dashed')

  await card.hover()
  await page.mouse.down()
  const cardBox = await card.boundingBox()
  const dropBox = await dropZone.boundingBox()
  if (!cardBox || !dropBox) throw new Error('carta o colonna non misurabile')
  // One intermediate point, clearly past the 6px activation distance, then the
  // real destination -- both via `page.mouse.move` (not `.hover()`, which jumps
  // in one step) so dnd-kit's own drag-start actually fires before the drop.
  await page.mouse.move(cardBox.x + cardBox.width / 2 + 20, cardBox.y + cardBox.height / 2 + 20)
  await page.mouse.move(dropBox.x + dropBox.width / 2, dropBox.y + dropBox.height / 2, { steps: 10 })
  await page.mouse.up()
}

/**
 * Creates a customer through the real UI (`/app/clienti` → "Nuovo cliente"), the
 * same form flow `crm.spec.ts`'s own customer-creation test drives, and returns the
 * generated, timestamp-suffixed name so a caller can find the row it just made
 * without racing any other customer already on screen.
 */
export async function createCustomer(page: Page): Promise<string> {
  const name = `Documenti ${Date.now()}`
  await page.goto('/app/clienti')
  await page.getByRole('button', { name: /nuovo cliente/i }).click()
  await page.getByLabel('Ragione sociale').fill(name)
  await page.getByRole('button', { name: 'Salva' }).click()
  await expect(page.getByText(name)).toBeVisible()
  return name
}

// -- Killing and relaunching the real API mid-suite --------------------------
//
// Fix round 1: pulled out of resilience.spec.ts (the only caller before this
// round) so a second spec -- the Kanban board has its own, separate copy of
// "a failed request must not look like an empty list" (routes/app/deal/
// index.tsx's `boardUnavailable`, with no `DataTable` underneath it to inherit
// coverage from) -- can drive the exact same kill-and-restore sequence without
// a second, drifting copy of this machinery. Same defaults apps/web/scripts/
// e2e-env.sh exports, read from `process.env` (inherited from apps/web/
// scripts/e2e.sh, which sources that file before launching `pnpm exec
// playwright test`).

const API_PORT = process.env.PIGROCRM_E2E_API_PORT ?? '8000'
const API_PIDFILE = process.env.PIGROCRM_E2E_API_PIDFILE ?? '/tmp/pigrocrm-e2e-api.pid'
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..')

async function pingApi(): Promise<boolean> {
  try {
    const response = await fetch(`http://localhost:${API_PORT}/openapi.json`)
    return response.ok
  } catch {
    return false
  }
}

async function waitUntil(condition: () => Promise<boolean>, timeoutMs: number, label: string): Promise<void> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await condition()) return
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  throw new Error(`timed out waiting for: ${label}`)
}

/** Reads apps/web/scripts/e2e-setup.sh's own pidfile and sends SIGTERM, then
 *  waits until the API genuinely stops answering -- not a fixed sleep, since
 *  how long a graceful uvicorn shutdown takes is not this suite's to guess. */
export async function killApi(): Promise<void> {
  const pid = Number(readFileSync(API_PIDFILE, 'utf-8').trim())
  process.kill(pid, 'SIGTERM')
  await waitUntil(async () => !(await pingApi()), 10_000, 'API to stop answering')
}

/** Relaunches the same `uv run uvicorn` process apps/web/scripts/e2e-setup.sh
 *  started, detached from this test process so it outlives the Playwright run,
 *  and overwrites the pidfile so apps/web/scripts/e2e-teardown.sh -- which runs
 *  after the whole suite, from a completely different process tree -- kills the
 *  right one at the end. Waits until the API genuinely answers again before
 *  returning, for the identical reason `killApi` waits on the way down. */
export async function relaunchApi(): Promise<void> {
  const child = spawn('uv', ['run', 'uvicorn', 'pigrocrm_api.main:app', '--port', API_PORT], {
    cwd: REPO_ROOT,
    detached: true,
    stdio: 'ignore',
    env: process.env,
  })
  child.unref()
  if (child.pid) writeFileSync(API_PIDFILE, String(child.pid))
  await waitUntil(pingApi, 30_000, 'API to answer again')
}
