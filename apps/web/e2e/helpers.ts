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
