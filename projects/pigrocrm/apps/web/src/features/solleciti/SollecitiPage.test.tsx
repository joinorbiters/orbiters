import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SollecitiPage } from './SollecitiPage'
import type { SollecitoCandidate } from './queries'
import { api } from '@/lib/api'

// `api` is an openapi-fetch client built at import time, so it is mocked as a module --
// the shape `GmailPanel.test.tsx` established and every feature test here follows.
// Stubbing `globalThis.fetch` would never be seen by it, and `vi.doMock` after this
// file's own static imports would apply to nothing. The hooks under test are the real
// ones; what is faked is the wire.
vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: { GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() },
  }
})

function ok(data: unknown) {
  return { data, response: new Response(null, { status: 200 }) } as never
}

function failed(error: unknown, status: number) {
  return { error, response: new Response(null, { status }) } as never
}

// ICU renders it-IT currency with a *non-breaking* space before the sign, and
// testing-library normalises it to an ordinary one before matching. The DOM assertion
// below therefore uses a plain space on purpose: an NBSP typed here would never match,
// and it would fail for a reason nobody can see in a source file.
// `features/time/columns.test.ts` asserts the NBSP directly on the formatter's return
// value, which is where that distinction is real.

const quiet: SollecitoCandidate = {
  invoice_id: 'i1',
  numero: '2026/01',
  data_fattura: '2026-07-01',
  data_scadenza: '2026-07-31',
  giorni_di_ritardo: 20,
  importo: '1200.00',
  cliente: 'Acme S.r.l.',
  customer_id: 'c1',
  solleciti_inviati: 0,
  ultimo_sollecito_il: null,
  prossimo_livello: 1,
  ultima_risposta_il: null,
}

const replied: SollecitoCandidate = {
  ...quiet,
  invoice_id: 'i2',
  numero: '2026/02',
  giorni_di_ritardo: 40,
  solleciti_inviati: 1,
  ultimo_sollecito_il: '2026-08-01',
  prossimo_livello: 2,
  ultima_risposta_il: '2026-08-12',
}

/** The server orders the list -- worst first, repliers last -- and the page renders that
 *  order. The fixtures are handed over already sorted for that reason: re-sorting in the
 *  browser is the duplication this feature refuses. */
function respond(candidates: SollecitoCandidate[] | { error: unknown; status: number }) {
  vi.mocked(api.GET).mockImplementation(((path: string) => {
    if (path === '/api/payment-reminders/candidates') {
      return Promise.resolve(
        'error' in candidates
          ? failed(candidates.error, candidates.status)
          : ok({ items: candidates, total: candidates.length }),
      )
    }
    // The composer's own reads, once a reminder has been prepared.
    if (path === '/api/email-drafts/{draft_id}') {
      return Promise.resolve(
        ok({
          id: 'd1',
          entity_type: 'customer',
          entity_id: 'c1',
          google_account_id: null,
          to_addresses: ['ada@acme.it'],
          cc_addresses: [],
          subject: 'Sollecito pagamento – 2026/01',
          body_markdown: 'Gentile Acme,\n\nFattura: 2026/01\nIBAN: IT60X054',
          attachment_version_ids: [],
          message_id_header: '<a.1@crm.example.it>',
          in_reply_to_message_id: null,
          send_state: 'bozza',
          send_attempted_at: null,
          last_error: null,
          sent_gmail_message_id: null,
          payment_reminder_id: 'r1',
          created_at: '2026-08-20T09:00:00Z',
          updated_at: '2026-08-20T09:00:00Z',
        }),
      )
    }
    if (path === '/api/documents') return Promise.resolve(ok({ items: [], total: 0 }))
    throw new Error(`unexpected GET ${path}`)
  }) as never)
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <SollecitiPage />
    </QueryClientProvider>,
  )
}

/** Data rows only: `getAllByRole('row')` includes the header. */
function dataRows() {
  return screen.getAllByRole('row').slice(1)
}

beforeEach(() => {
  vi.mocked(api.GET).mockReset()
  vi.mocked(api.POST).mockReset()
})

describe('SollecitiPage', () => {
  it('opens with its title as the page heading, and keeps it when the read fails', async () => {
    // The shell has had no top bar since the 2026-09-08 revision, so this `<h1>` is the
    // only thing naming the screen -- and a failed read is still this page, not an
    // unnamed panel holding a banner.
    respond([])
    mount()
    expect(await screen.findByRole('heading', { level: 1, name: 'Solleciti' })).toBeInTheDocument()
  })

  it('shows the days overdue, the amount and the date of the last reminder', async () => {
    // The boring part is *building this list* by crossing due dates against payments
    // against what has already gone out. Pressing the button was never the work, which
    // is why the columns are the work.
    respond([replied])

    mount()

    expect(await screen.findByText('2026/02')).toBeInTheDocument()
    expect(screen.getByText('40')).toBeInTheDocument()
    expect(screen.getByText('1.200,00 €')).toBeInTheDocument()
    expect(screen.getByText('01/08/2026')).toBeInTheDocument()
    expect(screen.getByText('2° sollecito')).toBeInTheDocument()
  })

  it('flags a client who has replied, and shows them last', async () => {
    // A reply is not a payment, and sometimes the reply is exactly what needs chasing.
    // So the candidate stays; it says so and it sinks. The order is the server's -- this
    // asserts the page renders it rather than inventing one of its own.
    respond([quiet, replied])

    mount()

    await screen.findByText('2026/01')
    const rows = dataRows()
    expect(rows[0]).toHaveTextContent('2026/01')
    expect(rows[1]).toHaveTextContent('2026/02')
    expect(rows[1]).toHaveTextContent('ha risposto il 12/08/2026')
    expect(rows[0]).not.toHaveTextContent('ha risposto')
  })

  it('renders an error rather than an empty table when the request failed', async () => {
    // The error branch before the loading one: on an error `isPending` is false while
    // `data` is still undefined. And an empty table is a *claim* -- "nobody owes you
    // anything" -- which is the last thing to say when the truth is "we could not ask".
    respond({ error: { detail: 'database non raggiungibile' }, status: 503 })

    mount()

    expect(await screen.findByRole('alert')).toHaveTextContent('database non raggiungibile')
    expect(screen.getByRole('heading', { level: 1, name: 'Solleciti' })).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByText(/Nessuna fattura da sollecitare/)).not.toBeInTheDocument()
    expect(screen.queryByText('Caricamento…')).not.toBeInTheDocument()
  })

  it('says the list is empty because nothing is due, not because something broke', async () => {
    respond([])

    mount()

    expect(await screen.findByText(/Nessuna fattura da sollecitare/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('creates the reminder without sending it, and opens it for review', async () => {
    // One press, one email -- and the press that creates is not the press that sends.
    // `POST /api/payment-reminders` writes the row and the draft; the draft goes out
    // through the same single send path as any other email, after a person has read it.
    respond([quiet])
    vi.mocked(api.POST).mockResolvedValue(
      ok({
        id: 'r1',
        invoice_id: 'i1',
        sequence: 1,
        sent_at: null,
        email_draft_id: 'd1',
        created_at: '2026-08-20T09:00:00Z',
      }),
    )

    mount()
    await userEvent.click(await screen.findByRole('button', { name: 'Prepara sollecito' }))

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith(
        '/api/payment-reminders',
        expect.objectContaining({ body: { invoice_id: 'i1' } }),
      ),
    )
    // Exactly one POST: preparing is one call, and it is not the send.
    expect(api.POST).toHaveBeenCalledTimes(1)
    expect(vi.mocked(api.POST).mock.calls.map((call) => call[0])).not.toContain(
      '/api/email-drafts/{draft_id}/send',
    )
    // And the letter opens for review, with the figures it will carry.
    expect(await screen.findByLabelText('Testo')).toHaveValue(
      'Gentile Acme,\n\nFattura: 2026/01\nIBAN: IT60X054',
    )
    expect(screen.getByText(/non è stato inviato/)).toBeInTheDocument()
  })

  it('keeps the list on screen and says why when preparing is refused', async () => {
    // The interval, the ceiling and «questo cliente non ha un indirizzo» all arrive as a
    // 409. The row must not vanish and the sentence must be the server's own.
    respond([quiet])
    vi.mocked(api.POST).mockResolvedValue(
      failed({ detail: 'un sollecito numero 1 per questa fattura esiste già' }, 409),
    )

    mount()
    await userEvent.click(await screen.findByRole('button', { name: 'Prepara sollecito' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('esiste già')
    expect(screen.getByText('2026/01')).toBeInTheDocument()
    // And the button comes back: a refusal is not a state the screen gets stuck in.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Prepara sollecito' })).toBeEnabled(),
    )
  })

  it('offers no bulk action, because a reminder is a commercial act', async () => {
    // Spec 7.2: a human every time, in this slice. What would have to exist for this to
    // become automatic -- a per-customer opt-in, a log of empty runs, an instant kill
    // switch -- does not exist, so it is not automatic, and there is no «invia tutti»
    // and no row checkbox to build one out of.
    respond([quiet, replied])

    mount()

    await screen.findByText('2026/01')
    expect(screen.queryByRole('button', { name: /Invia tutti|Seleziona tutt/ })).toBeNull()
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
    // One button per row and no more: the count is the assertion, because a "prepara
    // tutti" would most plausibly arrive as one extra button in the header.
    expect(screen.getAllByRole('button', { name: 'Prepara sollecito' })).toHaveLength(2)
  })

  it('never offers a Send button on the list itself', async () => {
    // Preparing and sending are two presses on purpose, and only the first one lives
    // here. A row-level «Invia» would be the second send path, which is where a double
    // send comes back.
    respond([quiet])

    mount()

    await screen.findByText('2026/01')
    expect(screen.queryByRole('button', { name: 'Invia' })).not.toBeInTheDocument()
    expect(within(screen.getByRole('table')).queryByRole('button', { name: /Invia/ })).toBeNull()
  })
})
