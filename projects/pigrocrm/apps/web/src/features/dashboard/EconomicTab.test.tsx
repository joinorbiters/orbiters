import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
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

/**
 * Two endpoints answer this screen since the «Stima fiscale» card moved into it:
 * `/api/analytics/panoramica` for the cards and the charts, `/api/analytics/fiscale` for
 * the card below them. Mocked by path rather than with one `mockResolvedValue`, because a
 * single answer for both would feed the panel a payload with no `avvertenza` and no year
 * -- green on an assertion about a card that never rendered what it renders in the app.
 */
function byPath(panoramica: unknown, fiscale: unknown = FISCALE) {
  return (path: string) =>
    Promise.resolve(path === '/api/analytics/fiscale' ? ok(fiscale) : ok(panoramica))
}

function failed(error: unknown, status: number) {
  return { error, response: new Response(null, { status }) } as never
}

function month(mese: number, incassato = '0.00', da_incassare = '0.00', bozze = '0.00', costi = '0.00') {
  return {
    anno: 2026,
    mese,
    incassato,
    da_incassare,
    bozze,
    costi,
    quote_andamento: { incassato: incassato === '0.00' ? 0 : 1, costi: costi === '0.00' ? 0 : 0.1 },
    quote_proiezione: {
      incassato: incassato === '0.00' ? 0 : 0.6,
      da_incassare: da_incassare === '0.00' ? 0 : 0.3,
      bozze: bozze === '0.00' ? 0 : 0.05,
      costi: costi === '0.00' ? 0 : 0.05,
    },
  }
}

const MESI = [
  month(1),
  month(2),
  month(3),
  month(4, '3990.00', '0.00', '0.00', '100.00'),
  month(5, '0.00', '0.00', '2500.00', '0.00'),
  month(6, '1200.00'),
  month(7, '6300.00', '0.00', '0.00', '97.50'),
  month(8, '7458.62', '6954.03', '0.00', '100.00'),
  month(9),
  month(10),
  month(11),
  month(12),
]

const FISCALE = {
  anno: 2026,
  stima: true,
  avvertenza: 'stima',
  ricavi: '20628.62',
  coefficiente_redditivita: '67.00',
  imponibile: '13821.18',
  aliquota_imposta_sostitutiva: '5.00',
  imposta_sostitutiva: '691.06',
  aliquota_inps: '26.07',
  contributi: '3423.02',
  reddito_netto_stimato: '16514.54',
  totale_dovuto: '4114.08',
}

const RESPONSE = {
  calcolato_alle: '2026-09-08T10:00:00Z',
  cassa: {
    anno: 2026,
    incassato: '20628.62',
    da_incassare: '6954.03',
    bozze: '2500.00',
    proiettato: '30082.65',
    costi: '297.50',
    lordo_effettivo: '20331.12',
    lordo_proiettato: '29785.15',
    mesi: MESI,
  },
  fiscale: FISCALE,
  fiscale_proiettato: { ...FISCALE, ricavi: '30082.65', imponibile: '20155.38', totale_dovuto: '5999.55' },
  netto_effettivo: '16217.04',
  netto_proiettato: '23785.60',
}

const PERIODO = { da: '2026-09-01', a: '2026-09-30' }

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
  it('asks for the year the period names, because cash and taxes are told by the year', async () => {
    vi.mocked(api.GET).mockImplementation(byPath(RESPONSE) as never)
    renderTab({ da: '2025-03-01', a: '2025-03-31' })
    await screen.findByText(/Vista economica 2025/)
    expect(api.GET).toHaveBeenCalledWith('/api/analytics/panoramica', {
      params: { query: { anno: 2025 } },
    })
  })

  it('shows the money figures from the API strings, cents included', async () => {
    vi.mocked(api.GET).mockImplementation(byPath(RESPONSE) as never)
    renderTab()
    const incassati = await screen.findByRole('group', { name: 'Ricavi incassati' })
    expect(incassati).toHaveTextContent('20.628,62 €')
    expect(screen.getByRole('group', { name: 'Ricavi proiettati' })).toHaveTextContent('30.082,65 €')
    expect(screen.getByRole('group', { name: 'Costi passivi' })).toHaveTextContent('297,50 €')
    expect(screen.getByRole('group', { name: 'Totale lordo effettivo' })).toHaveTextContent(
      '20.331,12 €',
    )
  })

  it('shows the fiscal estimate on collected and projected revenue', async () => {
    vi.mocked(api.GET).mockImplementation(byPath(RESPONSE) as never)
    renderTab()
    expect(await screen.findByRole('group', { name: 'Totale da saldare' })).toHaveTextContent(
      '4.114,08 €',
    )
    expect(screen.getByRole('group', { name: 'Totale da saldare con proiezione' })).toHaveTextContent(
      '5.999,55 €',
    )
    expect(screen.getByRole('group', { name: 'Totale netto ricavi' })).toHaveTextContent(
      '16.217,04 €',
    )
    expect(screen.getByRole('group', { name: 'Imponibile forfettario stimato' })).toHaveTextContent(
      '13.821,18 €',
    )
    // The rates are on the «Stima fiscale» card below, row by row, so the paragraph that
    // used to repeat them beside a link to another screen has nothing left to add.
    expect(screen.queryByRole('link', { name: /stima fiscale/i })).toBeNull()
    expect(screen.queryByText(/Stima basata sul regime forfettario/)).toBeNull()
  })

  it('shows cash alone, and no link out, when the estimate is not available', async () => {
    vi.mocked(api.GET).mockImplementation(
      byPath({
        ...RESPONSE,
        fiscale: null,
        fiscale_proiettato: null,
        netto_effettivo: null,
        netto_proiettato: null,
      }) as never,
    )
    renderTab()
    await screen.findByRole('group', { name: 'Ricavi incassati' })
    expect(screen.queryByRole('group', { name: 'Totale da saldare' })).toBeNull()
    expect(screen.getByText(/serve un profilo fiscale configurato/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /stima fiscale/i })).toBeNull()
  })

  it('carries the whole «Stima fiscale» card, between the figures and the charts', async () => {
    vi.mocked(api.GET).mockImplementation(byPath(RESPONSE) as never)
    const { container } = renderTab()

    // Every row of it, which is what «la scheda completa» means: the figures above answer
    // "how much do I owe", the card answers "out of what, at which rates".
    expect(await screen.findByText('Stima fiscale 2026')).toBeInTheDocument()
    for (const label of [
      'Coefficiente di redditività',
      'Imponibile',
      'Aliquota imposta sostitutiva',
      'Imposta sostitutiva',
      'Aliquota INPS',
      'Contributi INPS',
      'Reddito netto stimato',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    // The revenue row, addressed by the hint only it carries: its own label shares an
    // element with that hint, and its figure is also the «Ricavi incassati» card's.
    expect(screen.getByText(/fatture emesse nell'anno/)).toBeInTheDocument()
    expect(screen.getByText('67,00 %')).toBeInTheDocument()
    expect(screen.getByText('691,06 €')).toBeInTheDocument()
    expect(screen.getByText('16.514,54 €')).toBeInTheDocument()
    // The server's own caveat, above the figures it qualifies, as on the screen this card
    // came from.
    expect(screen.getByRole('note')).toBeInTheDocument()

    // Position asserted by document order: under the cards, before the charts. A card
    // that answers "at which rates" only after the reader has scrolled past the bar
    // charts is in the wrong place, and nothing but order can catch that.
    const cards = screen.getByRole('group', { name: 'Ricavi incassati' })
    const scheda = screen.getByText('Stima fiscale 2026')
    const grafico = screen.getByRole('figure', { name: 'Andamento economico 2026' })
    expect(cards.compareDocumentPosition(scheda) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(scheda.compareDocumentPosition(grafico) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(container.textContent).not.toMatch(/Apri la stima fiscale/)
  })

  it('asks the estimate for the year the period names', async () => {
    vi.mocked(api.GET).mockImplementation(byPath(RESPONSE, { ...FISCALE, anno: 2025 }) as never)
    renderTab({ da: '2025-03-01', a: '2025-03-31' })

    await screen.findByText('Stima fiscale 2025')
    expect(api.GET).toHaveBeenCalledWith('/api/analytics/fiscale', {
      params: { query: { anno: 2025 } },
    })
  })

  it('draws the two monthly charts with a legend and a table view each', async () => {
    vi.mocked(api.GET).mockImplementation(byPath(RESPONSE) as never)
    renderTab()
    const andamento = await screen.findByRole('figure', { name: 'Andamento economico 2026' })
    expect(within(andamento).getByRole('list', { name: 'Legenda' })).toHaveTextContent(
      'Ricavi incassatiCosti passivi',
    )
    const proiezione = screen.getByRole('figure', { name: 'Proiezione economica 2026' })
    expect(within(proiezione).getByRole('list', { name: 'Legenda' })).toHaveTextContent(
      'Da incassare',
    )
    // The tallest month is labelled directly; the table carries every value.
    expect(within(andamento).getAllByTestId('segment').length).toBeGreaterThan(0)
    expect(within(andamento).getByRole('table')).toHaveTextContent('7.980,00 €')
  })

  it('shows how old the figures are', async () => {
    vi.mocked(api.GET).mockImplementation(byPath(RESPONSE) as never)
    renderTab()
    expect(await screen.findByText(/Aggiornato/)).toBeInTheDocument()
  })

  it('renders an error banner and no figures when the request fails', async () => {
    vi.mocked(api.GET).mockResolvedValue(
      failed({ type: 'x', title: 'Errore', status: 500, detail: 'boom', code: 'domain_error' }, 500),
    )
    renderTab()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Ricavi incassati' })).toBeNull()
  })
})
