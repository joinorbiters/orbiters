/**
 * The three tabs and the period control, driven entirely by the search params.
 *
 * The component takes the search object and an `onSearchChange` callback rather than
 * reaching for the router itself, so the round trip the URL exists for is assertable:
 * what comes in as search props is what the tab requests, and what the controls change is
 * handed back as a new search object for the route to push into the URL.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DashboardPage } from './DashboardPage'
import type { DashboardSearch } from './search'
import { api } from '@/lib/api'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn(), PUT: vi.fn(), DELETE: vi.fn() } }
})

// The economic and operational tabs link out (the fiscal estimate, the three drill-through
// signals), and a `<Link>` outside a router throws. What those destinations are is asserted
// in each tab's own file; here the only question is which tab got mounted.
vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, children }: { to: string; children: React.ReactNode }) => <a href={to}>{children}</a>,
}))

const EMPTY_DASHBOARD = {
  periodo: { da: '2026-03-01', a: '2026-03-31' },
  calcolato_alle: '2026-03-15T10:00:00Z',
  pipeline: [],
  chiusure: { vinti: 0, persi: 0, valore_vinto: '0.00', tasso_conversione: null },
  offerte_in_attesa: [],
  offerte_in_attesa_totale: 0,
  chiusure_previste_30_giorni: 0,
  chiusure_non_attribuibili: 0,
  offerte_accettate_deal_non_vinto: 0,
}

const EMPTY_TOTALS = {
  ricavi: '0.00',
  costi_diretti: '0.00',
  costo_lavoro: '0.00',
  margine_lordo: '0.00',
  margine_percentuale: null,
  deal: 0,
}

const EMPTY_ECONOMIC = {
  periodo: { da: '2026-03-01', a: '2026-03-31' },
  calcolato_alle: '2026-03-15T10:00:00Z',
  pnl: {
    da: '2026-03-01',
    a: '2026-03-31',
    customer_id: null,
    chiusi: EMPTY_TOTALS,
    in_corso: EMPTY_TOTALS,
    spese_generali: '0.00',
    periodo_chiuso: false,
    voci_scritte_in_ritardo: 0,
    valore_maturato: '0.00',
    ore_fatturabili_non_fatturate: '0.00',
    ore_senza_tariffa: 0,
  },
  da_incassare: '0.00',
  scaduto: '0.00',
  fatture_emesse: 0,
}

const EMPTY_OPERATIONAL = {
  calcolato_alle: '2026-03-15T10:00:00Z',
  settimana: {
    da: '2026-03-09',
    a: '2026-03-15',
    giorni: [{ giorno: '2026-03-09', ore: '0.00' }],
    giorni_senza_ore: [],
    ore_totali: '0.00',
  },
  arretrato: {
    ore_fatturabili_non_fatturate: '0.00',
    valore_maturato: '0.00',
    voci_senza_tariffa: 0,
    voci: 0,
  },
  segnali: [],
  attivita_recenti: [],
}

/** One mock for three endpoints: which tab is mounted decides which one is called. */
const BY_PATH: Record<string, unknown> = {
  '/api/dashboard/commerciale': EMPTY_DASHBOARD,
  '/api/dashboard/economica': EMPTY_ECONOMIC,
  '/api/dashboard/operativa': EMPTY_OPERATIONAL,
}

const SEARCH: DashboardSearch = { tab: 'commerciale', da: '2026-03-01', a: '2026-03-31' }

function renderPage(search = SEARCH) {
  const onSearchChange = vi.fn()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <DashboardPage search={search} onSearchChange={onSearchChange} />
    </QueryClientProvider>,
  )
  return { onSearchChange }
}

beforeEach(() => {
  vi.mocked(api.GET).mockReset()
  vi.mocked(api.GET).mockImplementation(
    ((path: string) =>
      Promise.resolve({
        data: BY_PATH[path],
        response: new Response(null, { status: 200 }),
      })) as never,
  )
})

describe('DashboardPage', () => {
  it('renders the tab the URL names, not the first one', async () => {
    renderPage({ ...SEARCH, tab: 'economica' })
    expect(await screen.findByText(/conto economico del periodo/i)).toBeInTheDocument()
    expect(screen.queryByText(/pipeline aperta/i)).not.toBeInTheDocument()
    // One tab, one request: rendering all three and hiding two would open three snapshot
    // transactions to draw one screen.
    expect(api.GET).toHaveBeenCalledTimes(1)
    expect(api.GET).toHaveBeenCalledWith('/api/dashboard/economica', expect.anything())
  })

  it('mounts the operational tab with no period, because its question has none', async () => {
    renderPage({ ...SEARCH, tab: 'operativa' })
    expect(await screen.findByRole('table', { name: /ore per giorno/i })).toBeInTheDocument()
    expect(api.GET).toHaveBeenCalledTimes(1)
    // No second argument at all: not an empty query object, which would still put a `?` in
    // the URL of a question that has no period to ask about.
    expect(api.GET).toHaveBeenCalledWith('/api/dashboard/operativa')
  })

  it('passes the period from the URL through to the request', async () => {
    renderPage({ tab: 'commerciale', da: '2024-06-01', a: '2024-06-30' })
    expect(await screen.findByText(/nessun dato nel periodo/i)).toBeInTheDocument()
    expect(api.GET).toHaveBeenCalledWith('/api/dashboard/commerciale', {
      params: { query: { da: '2024-06-01', a: '2024-06-30' } },
    })
  })

  it('hands a changed period back for the URL rather than keeping it in local state', async () => {
    const { onSearchChange } = renderPage()
    await userEvent.click(screen.getByRole('button', { name: 'Anno' }))
    expect(onSearchChange).toHaveBeenCalledTimes(1)
    const [next] = onSearchChange.mock.calls[0]!
    expect(next.da).toMatch(/^\d{4}-01-01$/)
    expect(next.a).toMatch(/^\d{4}-12-31$/)
  })

  it('hands a changed tab back for the URL', async () => {
    const { onSearchChange } = renderPage()
    await userEvent.click(screen.getByRole('tab', { name: 'Operativa' }))
    expect(onSearchChange).toHaveBeenCalledWith({ tab: 'operativa' })
  })

  it('keeps a typed date in the URL too', () => {
    // `fireEvent`, not `userEvent.type`: an `<input type="date">` in jsdom does not accept
    // keystrokes the way a text input does, and a typing simulation would assert nothing.
    const { onSearchChange } = renderPage()
    fireEvent.change(screen.getByLabelText('Dal'), { target: { value: '2025-02-01' } })
    expect(onSearchChange).toHaveBeenLastCalledWith({ da: '2025-02-01', a: '2026-03-31' })
  })

  it('marks the current tab for a screen reader, not only with a colour', async () => {
    renderPage({ ...SEARCH, tab: 'operativa' })
    expect(screen.getByRole('tab', { name: 'Operativa' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Commerciale' })).toHaveAttribute(
      'aria-selected',
      'false',
    )
  })

  it('no longer explains away a tab that now exists', async () => {
    // §17's placeholders were the honest thing to show while slices 3 and 4 had not
    // landed. Both dashboards exist now, so the paragraph promising them would be the one
    // untrue sentence on the page -- and this is the assertion that would notice if one
    // were reinstated as a fallback for an empty response.
    renderPage({ ...SEARCH, tab: 'operativa' })
    await screen.findByRole('table', { name: /ore per giorno/i })
    expect(screen.queryByText(/arriva con il time tracking/i)).not.toBeInTheDocument()
    renderPage({ ...SEARCH, tab: 'economica' })
    await screen.findAllByText(/conto economico del periodo/i)
    expect(screen.queryByText(/arriva con la fatturazione/i)).not.toBeInTheDocument()
  })

  it('hides the period picker on the operational tab, whose figures have no period', async () => {
    // §6: the operational dashboard is the current week and a backlog -- the two things
    // that make no sense in the past. A picker that changed nothing would be a lie.
    renderPage({ ...SEARCH, tab: 'operativa' })
    expect(screen.queryByLabelText('Dal')).not.toBeInTheDocument()
    renderPage({ ...SEARCH, tab: 'commerciale' })
    expect(screen.getAllByLabelText('Dal').length).toBe(1)
  })
})
