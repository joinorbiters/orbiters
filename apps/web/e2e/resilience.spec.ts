import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn } from 'node:child_process'
import { expect, test } from '@playwright/test'
import { loginAsAdmin } from './helpers'

// Same defaults apps/web/scripts/e2e-env.sh exports -- read from `process.env`
// (inherited from apps/web/scripts/e2e.sh, which sources that file before
// launching `pnpm exec playwright test`) so this file never hand-maintains a
// second copy of the port/pidfile the shell scripts already own.
const API_PORT = process.env.PIGROCRM_E2E_API_PORT ?? '8000'
const PIDFILE = process.env.PIGROCRM_E2E_API_PIDFILE ?? '/tmp/pigrocrm-e2e-api.pid'
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

/** Relaunches the same `uv run uvicorn` process apps/web/scripts/e2e-setup.sh
 *  started, detached from this test process so it outlives the Playwright run,
 *  and overwrites the pidfile so apps/web/scripts/e2e-teardown.sh -- which runs
 *  after the whole suite, from a completely different process tree -- kills the
 *  right one at the end. */
function relaunchApi(): void {
  const child = spawn('uv', ['run', 'uvicorn', 'pigrocrm_api.main:app', '--port', API_PORT], {
    cwd: REPO_ROOT,
    detached: true,
    stdio: 'ignore',
    env: process.env,
  })
  child.unref()
  if (child.pid) writeFileSync(PIDFILE, String(child.pid))
}

/**
 * The last named gap: a failed request must read as "we could not ask", never
 * as a quiet, confident "there is nothing here" -- `QueryErrorBanner.tsx`'s own
 * docstring calls out the exact live defect this closes (every Kanban column at
 * 0/0,00 € with five "Nessun deal", or here, "Nessun cliente" on a list whose
 * request never actually completed). Self-contained on purpose: this test kills
 * the real API process mid-suite and relaunches it itself before finishing, so
 * every spec file after this one -- regardless of run order -- still has a
 * working backend, rather than relying on this file happening to run last.
 */
test('a dead API reads as a failure, not an empty list, and the app recovers once it returns', async ({ page }) => {
  test.setTimeout(60_000)
  expect(existsSync(PIDFILE), `${PIDFILE} missing -- run this suite via apps/web/scripts/e2e.sh`).toBe(true)

  await loginAsAdmin(page)
  await page.goto('/app/clienti')
  // Confirms the list genuinely works before the API dies, so what follows is a
  // regression against a real success, not against a page that never loaded.
  await expect(page.getByRole('button', { name: /nuovo cliente/i })).toBeVisible()

  const pid = Number(readFileSync(PIDFILE, 'utf-8').trim())
  process.kill(pid, 'SIGTERM')
  await waitUntil(async () => !(await pingApi()), 10_000, 'API to stop answering')

  try {
    // A brand-new query, not a reload: reloading the document would also re-run
    // `GET /api/auth/me`, and `AuthProvider`'s own try/catch (lib/auth.tsx)
    // treats *any* failure there -- including the network error this test just
    // caused -- as "not authenticated", bouncing to /login and masking the
    // thing actually under test. Typing into the search box changes
    // `useCustomers`' own query key instead, which has never been fetched
    // before and so has no stale-but-cached data to fall back on.
    await page.getByPlaceholder(/cerca per ragione sociale/i).fill('la richiesta deve fallire')

    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page.getByText('Nessun cliente. Creane uno per iniziare.')).not.toBeVisible()
  } finally {
    relaunchApi()
    await waitUntil(pingApi, 30_000, 'API to answer again')
  }

  // A real recovery, not merely "a banner appeared once" -- and specifically
  // *not* clearing the search box back to '' and re-checking, which was this
  // test's first draft: `queryKeys.customers({})` was already fetched
  // successfully before the API died and is still within react-query's own
  // 30s staleTime (lib/query.ts), so that query never re-hits the network at
  // all and the check would pass even against a *still-broken* relaunch --
  // caught by inspecting the relaunched process's own environment while
  // building this suite (see task-10-report.md). A full reload forces every
  // query to refetch from nothing, `GET /api/auth/me` included -- which is
  // also the one request that can only succeed if the relaunched process was
  // handed the *same* PIGROCRM_JWT_SECRET, since that is what verifies the
  // still-current session cookie's signature. Staying on /app/clienti here is
  // therefore proof of both a working database connection and a correctly
  // propagated secret, not just an HTTP server that answers.
  await page.reload()
  await expect(page).toHaveURL(/\/app\/clienti/)
  await expect(page.getByRole('alert')).not.toBeVisible()
  await expect(page.getByRole('button', { name: /nuovo cliente/i })).toBeVisible()
})
