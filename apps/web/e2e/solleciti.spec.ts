import { expect, test, type Page } from '@playwright/test'
import { loginAsAdmin } from './helpers'

/**
 * The solleciti page in a browser: what the list is for, and where it stops.
 *
 * Two claims only a browser can make. That the route exists, is reachable from the shell
 * and renders the register's own answer; and — the one this file exists for — that
 * «Prepara sollecito» **sends nothing**. Preparing and sending are two presses on
 * purpose, and a regression that quietly fused them would still pass every unit test on
 * either side of the boundary while putting a demand for money in a client's inbox that
 * nobody read. The assertion is on the *network*: every POST the page makes is recorded,
 * and the one that would have sent must not be among them.
 *
 * **What is stubbed, and why it has to be.** The second test drives the candidate list
 * and the reminder creation from `page.route`, the same way `gmail.spec.ts` stubs the
 * account health rather than driving a real consent flow. A candidate needs an invoice
 * that is genuinely a month past its due date, and this suite cannot make one: issuing
 * back-dated is refused by the register's own chronological-monotonicity rule the moment
 * any other spec has issued an invoice today (`economics.spec.ts` does, and runs first),
 * and the due date is derived from `fiscal_profile.giorni_scadenza`, which is shared
 * state every other spec depends on. `apps/api/tests/test_payment_reminders_router.py`
 * covers the real endpoints against a real register; what is left for a browser is the
 * wiring, and the stub is the API's own shape so that is exactly what is under test.
 *
 * **The send is never exercised, here or anywhere in this suite**, and that is not an
 * omission a later task fills in. `POST /api/email-drafts/{id}/send` would have to reach
 * `users.messages.send` at Gmail under a real OAuth grant; there is no Google here, and
 * the one call in the product with no idempotency key is not something a test suite
 * should be able to fire. `test_gmail_send.py` covers it against a fake transport.
 */

const CANDIDATES = '**/api/payment-reminders/candidates'
const CREATE = '**/api/payment-reminders'
const DRAFT = '**/api/email-drafts/*'

const CANDIDATE = {
  invoice_id: '00000000-0000-7000-8000-0000000000f1',
  numero: '2019/7',
  data_fattura: '2019-07-01',
  data_scadenza: '2019-07-31',
  giorni_di_ritardo: 40,
  importo: '1220.00',
  cliente: 'Acme S.r.l.',
  customer_id: '00000000-0000-7000-8000-0000000000c1',
  solleciti_inviati: 0,
  ultimo_sollecito_il: null,
  prossimo_livello: 1,
  ultima_risposta_il: null,
}

const REMINDER = {
  id: '00000000-0000-7000-8000-0000000000r1'.replace('r', 'a'),
  invoice_id: CANDIDATE.invoice_id,
  sequence: 1,
  // Null on everything this endpoint creates, because creating a reminder sends nothing.
  sent_at: null,
  email_draft_id: '00000000-0000-7000-8000-0000000000d1'.replace('d', 'b'),
  created_at: '2026-08-20T09:00:00Z',
}

const DRAFT_ROW = {
  id: REMINDER.email_draft_id,
  entity_type: 'customer',
  entity_id: CANDIDATE.customer_id,
  google_account_id: null,
  to_addresses: ['ada@acme.it'],
  cc_addresses: [],
  subject: `Sollecito pagamento – ${CANDIDATE.numero}`,
  body_markdown: [
    'Gentile Acme S.r.l.,',
    '',
    `Fattura: ${CANDIDATE.numero}`,
    'Scadenza: 31/07/2019',
    'Importo: 1.220,00 €',
    'IBAN: IT60X0542811101000000123456',
  ].join('\n'),
  attachment_version_ids: [],
  message_id_header: '<a.1@crm.example.it>',
  in_reply_to_message_id: null,
  send_state: 'bozza',
  send_attempted_at: null,
  last_error: null,
  sent_gmail_message_id: null,
  payment_reminder_id: REMINDER.id,
  created_at: '2026-08-20T09:00:00Z',
  updated_at: '2026-08-20T09:00:00Z',
}

async function json(page: Page, pattern: string, body: unknown, status = 200): Promise<void> {
  await page.route(pattern, async (route) => {
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

test('the page is reachable from the shell and reads the real register', async ({ page }) => {
  // No stub at all here: this is the route, the navigation entry and the real endpoint.
  // The seeded database has no overdue invoice, so the honest answer is the empty state --
  // and «Nessuna fattura da sollecitare» is a claim about the register, not about a
  // request that failed, which is the distinction the page is built around.
  await loginAsAdmin(page)

  await page.getByRole('link', { name: 'Solleciti' }).click()

  await expect(page).toHaveURL(/\/app\/solleciti$/)
  await expect(page.getByRole('heading', { name: 'Solleciti' })).toBeVisible()
  await expect(page.getByText(/Nessuna fattura da sollecitare/)).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('preparing a reminder opens it for review and sends nothing', async ({ page }) => {
  await loginAsAdmin(page)
  await json(page, CANDIDATES, { items: [CANDIDATE], total: 1 })
  await json(page, DRAFT, DRAFT_ROW)
  // Registered last so it does not shadow `/candidates`, which shares its prefix:
  // Playwright matches routes most-recently-registered first.
  await json(page, CREATE, REMINDER, 201)

  await page.goto('/app/solleciti')
  const row = page.getByRole('row').filter({ hasText: CANDIDATE.numero })
  await expect(row).toBeVisible()
  await expect(row).toContainText('1.220,00')
  await expect(row).toContainText('1° sollecito')

  // Every POST the page makes from here on, so "nothing was sent" is a fact about the
  // network rather than about the absence of a button.
  const posted: string[] = []
  page.on('request', (issued) => {
    if (issued.method() === 'POST') posted.push(new URL(issued.url()).pathname)
  })

  await row.getByRole('button', { name: 'Prepara sollecito' }).click()

  // The letter opens for review. The words go out in the operator's name, so they read
  // them first -- the invoice number, the due date, the frozen figure and where to pay.
  const testo = page.getByLabel('Testo')
  await expect(testo).toContainText(`Fattura: ${CANDIDATE.numero}`)
  await expect(testo).toContainText('IBAN:')
  await expect(page.getByText(/non è stato inviato/)).toBeVisible()

  expect(posted).toContain('/api/payment-reminders')
  expect(posted.filter((path) => path.endsWith('/send'))).toEqual([])
})

test('the list offers no bulk action', async ({ page }) => {
  // Spec 7.2: a human every time, in this slice. What would have to exist for a reminder
  // run to be safe to automate -- a per-customer opt-in, a log of runs that sent nothing,
  // an instant kill switch -- does not exist, so it is not automatic. Asserted in the
  // browser as well as in the unit test because "there is no «invia tutti»" is a claim
  // about the whole page, including whatever the shell puts around it.
  await loginAsAdmin(page)
  await json(page, CANDIDATES, { items: [CANDIDATE], total: 1 })

  await page.goto('/app/solleciti')

  await expect(page.getByRole('row').filter({ hasText: CANDIDATE.numero })).toBeVisible()
  await expect(page.getByRole('button', { name: /Invia tutti|Seleziona tutt/ })).toHaveCount(0)
  await expect(page.getByRole('checkbox')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Invia' })).toHaveCount(0)
})
