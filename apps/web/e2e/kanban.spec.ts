import { expect, test } from '@playwright/test'
import { dragDealToStage, loginAsAdmin } from './helpers'

// The default 1280px viewport only fits three `w-72` (18rem) Kanban columns
// next to the sidebar before `KanbanBoard`'s own `overflow-x-auto` kicks in --
// fine for crm.spec.ts's Lead-to-Offerta drag (3rd column), not for this file,
// which adds a 7th. Confirmed live as the actual cause of this test's first
// failure: the drop landed with no `over` target at all (dnd-kit still fired
// its own "was dropped" a11y announcement, but `resolveMove` -- KanbanBoard.tsx
// -- returned `null` for an undefined `overId`), so no PATCH was ever sent, no
// toast appeared, and the card simply never moved -- which looks deceptively
// like "the card stayed in Lead", the exact final state a *correct* rejection
// also produces, for a completely different and untested reason.
test.use({ viewport: { width: 2200, height: 1000 } })

test.beforeEach(async ({ page }) => {
  await loginAsAdmin(page)
})

/**
 * The Kanban board's own cache can go stale relative to the server mid-session
 * -- `useMoveDeal`'s docstring (features/deals/queries.ts) documents this
 * exact shape of bug for a deal deleted out from under a loaded board, and
 * `useStages`' own docstring documents the symmetric case for a *stage*
 * deleted server-side, which "kept rendering as a phantom Kanban column ...
 * until the next full reload". This drives a drop onto exactly that phantom
 * column: a pipeline stage created and then deleted entirely within this test
 * (never touching the shared default stages any other spec in this suite
 * relies on), so the deal itself is untouched throughout and "the card goes
 * back to where it was" is a real, persistent fact -- not merely "the record
 * happens to be gone so of course it isn't anywhere".
 */
test('a move the server refuses puts the card back in its original column and says why', async ({ page }) => {
  const customerName = `Kanban Reject ${Date.now()}`
  await page.goto('/app/clienti')
  await page.getByRole('button', { name: /nuovo cliente/i }).click()
  await page.getByLabel('Ragione sociale').fill(customerName)
  await page.getByRole('button', { name: 'Salva' }).click()
  await expect(page.getByText(customerName)).toBeVisible()

  // A doomed stage, created (and about to be deleted) entirely within this
  // test -- mirrors PipelinePanel.tsx's own `submit` body exactly.
  const stageName = `Rifiuto ${Date.now()}`
  const stageResponse = await page.request.post('/api/pipeline-stages', {
    data: { nome: stageName, posizione: 99, probabilita_default: 50, tipo: 'open' },
  })
  expect(stageResponse.ok()).toBe(true)
  const stage = (await stageResponse.json()) as { id: string }

  const dealName = `Deal Reject ${Date.now()}`
  await page.goto('/app/deal')
  await page.getByRole('button', { name: /nuovo deal/i }).click()
  await page.getByLabel(/^Cliente/).click()
  await page.getByRole('option', { name: customerName }).click()
  // Anchored regex, not `exact: true`: "Nome" is required, so its real
  // accessible name is "Nome *" (DynamicFieldRenderer's RequiredMark) -- see
  // crm.spec.ts's identical comment for the two ways this can be gotten
  // wrong (an exact match against plain "Nome" finds nothing; a bare
  // substring match on "Nome" alone would be fine here, since this form has
  // no "Cognome" to collide with, but the anchored form costs nothing and
  // stays consistent with the one call site that does need it).
  await page.getByLabel(/^Nome\b/).fill(dealName)

  const [createResponse] = await Promise.all([
    page.waitForResponse(
      (res) => res.request().method() === 'POST' && res.url().includes('/api/deals'),
    ),
    page.getByRole('button', { name: 'Salva' }).click(),
  ])
  const deal = (await createResponse.json()) as { id: string }

  const leadColumn = page
    .locator('div.flex.w-72.shrink-0.flex-col')
    .filter({ has: page.getByRole('heading', { name: 'Lead', exact: true }) })
  const doomedColumn = page
    .locator('div.flex.w-72.shrink-0.flex-col')
    .filter({ has: page.getByRole('heading', { name: stageName, exact: true }) })
  await expect(leadColumn.getByText(dealName, { exact: true })).toBeVisible()
  await expect(doomedColumn).toBeVisible()

  // The board's own `stages`/`deals` queries are both cached (30s staleTime,
  // features/deals/queries.ts) -- deleting the stage here does not, by itself,
  // change anything already rendered above.
  const deleteResponse = await page.request.delete(`/api/pipeline-stages/${stage.id}`)
  expect(deleteResponse.ok()).toBe(true)

  await dragDealToStage(page, dealName, stageName)

  // `PipelineService.get` raises `NotFound("pipeline_stage", stage_id)`
  // (packages/core/src/pigrocrm/core/pipeline/service.py) before `move_stage`
  // ever touches the deal itself -- asserted by this test's own stage id, not
  // a loose "something failed".
  await expect(page.getByText(new RegExp(`pipeline_stage ${stage.id} not found`, 'i'))).toBeVisible()

  // The deal itself was never touched server-side, so it is still, genuinely,
  // in Lead -- not merely "not visible anywhere else because the record is
  // gone", the trap a same-shaped test built around deleting the *deal*
  // instead would fall into.
  await expect(leadColumn.getByText(dealName, { exact: true })).toBeVisible()

  await page.reload()
  await expect(leadColumn.getByText(dealName, { exact: true })).toBeVisible()

  // And through the API, not only the UI: the deal's own `pipeline_stage_id`
  // never changed server-side at all -- the rejection happened before
  // `move_stage` ever wrote anything.
  const finalDeal = await (await page.request.get(`/api/deals/${deal.id}`)).json()
  const leadStage = await (await page.request.get('/api/pipeline-stages')).json()
  const leadId = (leadStage as { id: string; nome: string }[]).find((s) => s.nome === 'Lead')?.id
  expect(finalDeal.pipeline_stage_id).toBe(leadId)
})
