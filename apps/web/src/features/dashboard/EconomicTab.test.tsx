/**
 * §5's tab. Every figure comes from the API already summed; this file asserts on the four
 * things §5 and §5.1-5.3 say must be true of how they are *presented*, because that is the
 * half a backend test cannot reach.
 *
 * `vi.mock('@/lib/api')` and not a stubbed `globalThis.fetch`: `api` is an openapi-fetch
 * client built at import time, so replacing `fetch` afterwards changes nothing. `msw` is
 * not a dependency of this project.
 *
 * `@tanstack/react-router` is mocked with a `Link` that renders the `to` and `search` it
 * was given as a real `href`. That is not a tautology: what is asserted is the destination
 * *this component chose*, and the assertion is written against the string the server sent
 * in `collegamento`, so the two cannot drift apart without a failure here.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { EconomicTab } from './EconomicTab'
import { api } from '@/lib/api'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn(), PUT: vi.fn(), DELETE: vi.fn() } }
})

vi.mock('@tanstack/react-router', () => ({
  Link: ({
    to,
    children,
    ...rest
  }: {
    to: string
    children: React.ReactNode
  } & Record<string, unknown>) => (
    <a href={to} {...rest}>
      {children}
    </a>
  ),
}))

function ok(data: unknown) {
  return { data, response: new Response(null, { status: 200 }) } as never
}

function failed(error: unknown, status: number) {
  return { error, response: new Response(null, { status }) } as never
}

const CLOSED = {
  ricavi: '15000.00',
  costi_diretti: '2000.00',
  costo_lavoro: '6000.00',
  margine_lordo: '7000.00',
  margine_percentuale: '46.67',
  deal: 4,
}

const RESPONSE = {
  periodo: { da: '2026-03-01', a: '2026-03-31' },
  calcolato_alle: '2026-03-15T10:00:00Z',
  pnl: {
    da: '2026-03-01',
    a: '2026-03-31',
    customer_id: null,
    chiusi: CLOSED,
    // A running column with no closed deal behind its percentage: `null`, which must read
    // as a dash and never as 0%.
    in_corso: { ...CLOSED, ricavi: '3000.00', margine_percentuale: null },
    spese_generali: '900.00',
    periodo_chiuso: false,
    voci_scritte_in_ritardo: 2,
    valore_maturato: '4500.00',
    ore_fatturabili_non_fatturate: '90.00',
    ore_senza_tariffa: 3,
  },
  da_incassare: '12200.00',
  scaduto: '3050.00',
  fatture_emesse: 6,
}

const PERIODO = { da: '2026-03-01', a: '2026-03-31' }

function renderTab(periodo = PERIODO) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <EconomicTab periodo={periodo} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(api.GET).mockReset()
})

describe('EconomicTab', () => {
  it('asks for the period it was given, so a shared link answers its own question', async () => {
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab({ da: '2025-01-01', a: '2025-12-31' })
    await screen.findByRole('table', { name: /conto economico/i })
    expect(api.GET).toHaveBeenCalledWith('/api/dashboard/economica', {
      params: { query: { da: '2025-01-01', a: '2025-12-31' } },
    })
  })

  it('labels revenue in full, never just "Fatturato"', async () => {
    // §5.1: three extra words on a card are the price of not having two users read the
    // same figure as two different things.
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByText(/fatturato \(imponibile, emesso\)/i)).toBeInTheDocument()
    // And the bare word appears nowhere on its own: a second, shorter label for the same
    // figure is exactly the ambiguity the long one was chosen to remove.
    expect(screen.queryByText('Fatturato')).not.toBeInTheDocument()
  })

  it('shows the margin in two columns and no box holding their sum', async () => {
    // Slice 4 §7.4: adding a finished job's margin to a half-done one produces a figure
    // that is neither, and that moves every week for reasons which are not performance.
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByRole('columnheader', { name: /deal chiusi/i })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: /deal in corso/i })).toBeInTheDocument()
    expect(screen.queryByText(/margine totale/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/margine complessivo/i)).not.toBeInTheDocument()
    // The two margins are rendered, each in its own cell, and there is no third one. The
    // sum of 7000 and 7000 would be 14.000,00 €, and it must not be anywhere.
    expect(screen.getAllByText('7.000,00 €')).toHaveLength(2)
    expect(screen.queryByText('14.000,00 €')).not.toBeInTheDocument()
  })

  it('marks the closed-deals column as the reportable one', async () => {
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByText(/cifra riportabile/i)).toBeInTheDocument()
  })

  it('renders a null margin percentage as a dash and never as 0%', async () => {
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    // `in_corso.margine_percentuale` is null in the fixture; `chiusi`'s is not.
    expect(await screen.findByText('46,67%')).toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(screen.queryByText('0,00%')).not.toBeInTheDocument()
  })

  it('formats every money figure from the API string, cents included', async () => {
    // `Number("0.29") * 100` is 28.999999999999996. Nothing here parses a money string at
    // all, and this is the assertion that would notice if somebody reintroduced the parse.
    vi.mocked(api.GET).mockResolvedValue(
      ok({ ...RESPONSE, da_incassare: '12200.29', scaduto: '3050.01' }),
    )
    renderTab()
    expect(await screen.findByText('12.200,29 €')).toBeInTheDocument()
    // useGrouping: 'always' -- it-IT withholds the separator below five integer digits.
    expect(screen.getByText('3.050,01 €')).toBeInTheDocument()
  })

  it('renders "Scaduto" as a subset indented under "Da incassare"', async () => {
    // §5.2: a subset shown as one, never a second addable voice.
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    const overdue = await screen.findByTestId('scaduto')
    expect(overdue).toHaveAttribute('data-subset-of', 'da-incassare')
    expect(overdue).toHaveTextContent(/di cui scaduto/i)
    // Structural, not only a label: the overdue figure is rendered *inside* the receivable
    // card, so no layout change can leave it standing beside it as a second line.
    expect(overdue.closest('[data-testid="da-incassare"]')).not.toBeNull()
    // And their sum -- 15.250,00 € -- appears nowhere.
    expect(screen.queryByText('15.250,00 €')).not.toBeInTheDocument()
  })

  it('keeps "Da incassare" out of the P&L block', async () => {
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    const receivable = await screen.findByTestId('da-incassare')
    // A receivable is not revenue (§5.2): it is money owed, VAT included. Rendering it
    // inside the P&L block would invite exactly the addition the label forbids.
    expect(receivable.closest('[data-block="pnl"]')).toBeNull()
    expect(screen.getByTestId('da-incassare')).toHaveTextContent(/non entra in nessun margine/i)
  })

  it('shows the informative rows under a heading that is not "ricavi"', async () => {
    // §5: "Compaiono sotto un'intestazione diversa da «ricavi» e non entrano in nessun
    // margine", and the label carries the scope.
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByText(/valore maturato non fatturato/i)).toBeInTheDocument()
    const section = screen.getByTestId('maturato')
    expect(section).toHaveTextContent(/nel periodo/i)
    expect(section).toHaveTextContent(/non sono ricavi/i)
    // The scope is on the heading, not in a footnote: this section is about the period,
    // and the operational tab's backlog -- the same quantity without a period -- is not
    // on this page at all.
    expect(section.closest('[data-block="pnl"]')).toBeNull()
  })

  it('says whether the period can still move', async () => {
    // Slice 4 §6.4, and §5: beside the total, not in a footnote.
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByText(/periodo non chiuso/i)).toBeInTheDocument()
    expect(screen.getByText(/2 voci scritte in ritardo/i)).toBeInTheDocument()
  })

  it('says the period is closed when it is, and mentions no late entries when there are none', async () => {
    // The negative of the assertion above, without which "Periodo non chiuso" could be a
    // constant string and the test would not know.
    vi.mocked(api.GET).mockResolvedValue(
      ok({
        ...RESPONSE,
        pnl: { ...RESPONSE.pnl, periodo_chiuso: true, voci_scritte_in_ritardo: 0 },
      }),
    )
    renderTab()
    expect(await screen.findByText(/periodo chiuso/i)).toBeInTheDocument()
    expect(screen.queryByText(/periodo non chiuso/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/scritte in ritardo/i)).not.toBeInTheDocument()
  })

  it('links to the fiscal estimate instead of showing a number', async () => {
    // §5.3: a dashboard is the screen most likely to end up in a screenshot.
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    const link = await screen.findByRole('link', { name: /stima fiscale/i })
    expect(link).toHaveAttribute('href', '/app/analisi/fiscale')
    for (const forbidden of [/imposta sostitutiva/i, /contributi/i, /netto stimato/i]) {
      expect(screen.queryByText(forbidden)).not.toBeInTheDocument()
    }
  })

  it('shows no comparison with the same period last year', async () => {
    // §5.3: the right behaviour when the prior period is partly written depends on
    // period_locks in a way nobody has exercised. A wrong comparison is worse than none.
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    await screen.findByText(/fatturato \(imponibile, emesso\)/i)
    expect(screen.queryByText(/anno precedente/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/rispetto a/i)).not.toBeInTheDocument()
  })

  it('shows how old the figures are', async () => {
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByText(/aggiornato/i)).toBeInTheDocument()
  })

  it('renders an error banner and no figures when the request fails', async () => {
    vi.mocked(api.GET).mockResolvedValue(
      failed({ title: 'Errore', detail: 'Non disponibile', code: 'unavailable' }, 500),
    )
    renderTab()
    expect(await screen.findByRole('alert')).toHaveTextContent('Non disponibile')
    // The error branch is checked *before* the loading branch: on a failure `isPending` is
    // false while `data` is still undefined, so a single `isPending || !data` guard answers
    // a failed read with a spinner that never resolves. And no figures, no table, no
    // freshness stamp -- a dashboard drawn empty after a failure says "there is nothing"
    // when the truth is "I do not know".
    expect(screen.queryByText(/fatturato/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByText(/aggiornato/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /stima fiscale/i })).not.toBeInTheDocument()
  })
})
