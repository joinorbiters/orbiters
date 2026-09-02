/**
 * §4's tab. Properties a snapshot test would not reach: the figures are rendered as the
 * strings the API sent, the weighted value is labelled a *stima* and never sits in the
 * same total as revenue, the period in the URL is the period actually requested, and a
 * failed request renders an error rather than an empty dashboard.
 *
 * `vi.mock('@/lib/api')`, not a stubbed `globalThis.fetch`: `api` is an openapi-fetch
 * client built at import time, so replacing `fetch` afterwards changes nothing.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CommercialTab } from './CommercialTab'
import { api } from '@/lib/api'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn(), PUT: vi.fn(), DELETE: vi.fn() } }
})

function ok(data: unknown) {
  return { data, response: new Response(null, { status: 200 }) } as never
}

function failed(error: unknown, status: number) {
  return { error, response: new Response(null, { status }) } as never
}

const RESPONSE = {
  periodo: { da: '2026-03-01', a: '2026-03-31' },
  calcolato_alle: '2026-03-15T10:00:00Z',
  pipeline: [
    {
      stage_id: 's1',
      stage_code: 'lead',
      stage_nome: 'Lead',
      posizione: 0,
      numero: 4,
      valore_totale: '3000.00',
      senza_valore: 1,
      valore_ponderato: '610.00',
    },
    {
      stage_id: 's2',
      stage_code: 'offerta',
      stage_nome: 'Offerta',
      posizione: 2,
      numero: 1,
      valore_totale: '500.00',
      senza_valore: 0,
      valore_ponderato: '250.00',
    },
  ],
  chiusure: { vinti: 3, persi: 1, valore_vinto: '15000.00', tasso_conversione: '75.00' },
  offerte_in_attesa: [
    {
      document_id: 'd1',
      titolo: 'Offerta impianti',
      deal_id: 'x',
      customer_id: null,
      stato_dal: '2026-02-01',
      giorni: 42,
    },
  ],
  offerte_in_attesa_totale: 1,
  chiusure_previste_30_giorni: 2,
  chiusure_non_attribuibili: 7,
  offerte_accettate_deal_non_vinto: 2,
}

const PERIODO = { da: '2026-03-01', a: '2026-03-31' }

function renderTab(periodo = PERIODO) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CommercialTab periodo={periodo} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(api.GET).mockReset()
})

describe('CommercialTab', () => {
  it('asks for the period it was given, so a shared link answers its own question', async () => {
    // The other half of the URL round trip: `periodo.test.ts` proves the search params are
    // read back, this proves they reach the request instead of being decoration.
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab({ da: '2025-01-01', a: '2025-12-31' })
    await screen.findByRole('table', { name: /pipeline aperta/i })
    expect(api.GET).toHaveBeenCalledWith('/api/dashboard/commerciale', {
      params: { query: { da: '2025-01-01', a: '2025-12-31' } },
    })
  })

  it('renders the pipeline as a table with the values the API sent', async () => {
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    const table = await screen.findByRole('table', { name: /pipeline aperta/i })
    expect(within(table).getByRole('rowheader', { name: 'Lead' })).toBeInTheDocument()
    expect(within(table).getByRole('rowheader', { name: 'Offerta' })).toBeInTheDocument()
  })

  it('formats every money figure from the API string, cents included', async () => {
    // `Number("0.29") * 100` is 28.999999999999996. Nothing here parses a money string at
    // all -- `Intl.NumberFormat.format` takes it verbatim -- and this is the assertion
    // that would notice if somebody reintroduced the parse.
    vi.mocked(api.GET).mockResolvedValue(
      ok({
        ...RESPONSE,
        chiusure: { ...RESPONSE.chiusure, valore_vinto: '15000.29' },
      }),
    )
    renderTab()
    expect(await screen.findByText('15.000,29 €')).toBeInTheDocument()
    // useGrouping: 'always' -- it-IT withholds the separator below five integer digits.
    expect(screen.getByText('3.000,00 €')).toBeInTheDocument()
  })

  it('labels the weighted value a stima, in a column of its own', async () => {
    // §4: "Etichettata *stima*, in una colonna con un'intestazione diversa da qualunque
    // cifra di fatturato". A weighted pipeline figure read as revenue is the exact
    // confusion this label prevents.
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByRole('columnheader', { name: /stima/i })).toBeInTheDocument()
    expect(screen.getByText('610,00 €')).toBeInTheDocument()
  })

  it('shows deals without a value separately and never as zero', async () => {
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByRole('columnheader', { name: /senza valore/i })).toBeInTheDocument()
  })

  it('shows the conversion rate, and shows a dash rather than 0% when it is null', async () => {
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    const { unmount } = renderTab()
    expect(await screen.findByText('75,00%')).toBeInTheDocument()
    unmount()

    vi.mocked(api.GET).mockResolvedValue(
      ok({ ...RESPONSE, chiusure: { ...RESPONSE.chiusure, tasso_conversione: null } }),
    )
    renderTab()
    // "0%" would say "I lost everything"; null says "nothing closed". Different facts.
    expect(await screen.findByText('—')).toBeInTheDocument()
    expect(screen.queryByText('0,00%')).not.toBeInTheDocument()
  })

  it('declares the deals that cannot be attributed to a period', async () => {
    // §4.1: `chiuso_il` is not backfilled, so the dashboard says so instead of counting
    // those rows as zero or putting them in the wrong month.
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByText(/7 deal chiusi prima/i)).toBeInTheDocument()
    expect(screen.getByText(/non sono attribuibili/i)).toBeInTheDocument()
  })

  it('says nothing about unattributable deals when there are none', async () => {
    // A permanent "0 deal chiusi prima..." would be a caveat about nothing, printed for
    // every user forever.
    vi.mocked(api.GET).mockResolvedValue(ok({ ...RESPONSE, chiusure_non_attribuibili: 0 }))
    renderTab()
    await screen.findByRole('table', { name: /pipeline aperta/i })
    expect(screen.queryByText(/non sono attribuibili/i)).not.toBeInTheDocument()
  })

  it('shows the age of each pending offer', async () => {
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByText(/42 giorni/i)).toBeInTheDocument()
  })

  it('says the age is unknown rather than printing zero days', async () => {
    // `giorni: null` means `stato_dal` is unknown; "0 giorni" would read as "sent today".
    vi.mocked(api.GET).mockResolvedValue(
      ok({
        ...RESPONSE,
        offerte_in_attesa: [{ ...RESPONSE.offerte_in_attesa[0]!, stato_dal: null, giorni: null }],
      }),
    )
    renderTab()
    expect(await screen.findByText(/data ignota/i)).toBeInTheDocument()
  })

  it('states the inconsistency signal as a count, and promises no list that does not exist', async () => {
    // The brief pointed this at `/app/documenti?solo_deal_non_vinto=true`. There is no
    // `/app/documenti` list route in this codebase at all -- only
    // `/app/documenti/$documentId` -- and no list page anywhere reads a search parameter.
    // A link under a label promising a filtered list, landing on a 404, is the defect
    // Task A13 found in its own brief. Until the drill-through exists the signal is a
    // number with its explanation, which is honest.
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByText(/offerta accettata, deal non vinto/i)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /offerta accettata/i })).not.toBeInTheDocument()
  })

  it('renders an error banner and no dashboard when the request fails', async () => {
    vi.mocked(api.GET).mockResolvedValue(
      failed({ title: 'Errore', detail: 'Non disponibile', code: 'unavailable' }, 500),
    )
    renderTab()
    expect(await screen.findByRole('alert')).toHaveTextContent('Non disponibile')
    expect(screen.queryByRole('table', { name: /pipeline aperta/i })).not.toBeInTheDocument()
    // The rule from §8.6, applied here too: an empty dashboard drawn after a failure says
    // "there is nothing" when the truth is "I do not know". The error branch is also
    // checked *before* the loading branch, because on a failure `isPending` is false while
    // `data` is still undefined -- a single `isPending || !data` guard answers a failed
    // read with a spinner that never resolves.
    expect(screen.queryByText(/nessun dato/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/aggiornato/i)).not.toBeInTheDocument()
  })

  it('shows how old the figures are', async () => {
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByText(/aggiornato/i)).toBeInTheDocument()
  })

  it('renders an empty pipeline as an empty state, not as a bar of nothing', async () => {
    vi.mocked(api.GET).mockResolvedValue(ok({ ...RESPONSE, pipeline: [] }))
    renderTab()
    expect(await screen.findByText(/nessun dato nel periodo/i)).toBeInTheDocument()
  })
})
