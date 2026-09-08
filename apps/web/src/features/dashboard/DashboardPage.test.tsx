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


const EMPTY_OVERVIEW = {
  calcolato_alle: '2026-03-15T10:00:00Z',
  cassa: {
    anno: 2026,
    incassato: '0.00',
    da_incassare: '0.00',
    bozze: '0.00',
    proiettato: '0.00',
    costi: '0.00',
    lordo_effettivo: '0.00',
    lordo_proiettato: '0.00',
    mesi: [],
  },
  fiscale: null,
  fiscale_proiettato: null,
  netto_effettivo: null,
  netto_proiettato: null,
}


/** One mock for three endpoints: which tab is mounted decides which one is called. */
const BY_PATH: Record<string, unknown> = {
  '/api/dashboard/commerciale': EMPTY_DASHBOARD,
  '/api/analytics/panoramica': EMPTY_OVERVIEW,
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
    expect(await screen.findByRole('group', { name: 'Ricavi incassati' })).toBeInTheDocument()
    expect(screen.queryByText(/pipeline aperta/i)).not.toBeInTheDocument()
    // One tab, one request: rendering all three and hiding two would open three snapshot
    // transactions to draw one screen.
    expect(api.GET).toHaveBeenCalledTimes(1)
    expect(api.GET).toHaveBeenCalledWith('/api/analytics/panoramica', expect.anything())
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
    await userEvent.click(screen.getByRole('tab', { name: 'Economica' }))
    expect(onSearchChange).toHaveBeenCalledWith({ tab: 'economica' })
  })

  it('keeps a typed date in the URL too', () => {
    // `fireEvent`, not `userEvent.type`: an `<input type="date">` in jsdom does not accept
    // keystrokes the way a text input does, and a typing simulation would assert nothing.
    const { onSearchChange } = renderPage()
    fireEvent.change(screen.getByLabelText('Dal'), { target: { value: '2025-02-01' } })
    expect(onSearchChange).toHaveBeenLastCalledWith({ da: '2025-02-01', a: '2026-03-31' })
  })

})

describe('DashboardPage, the page intestazione', () => {
  /**
   * Since the 2026-09-08 revision the dashboard owns its own header rather than being
   * given one by the route: the tabs are part of the intestazione (§4, «Sotto, quando
   * servono, le tab»), and the period picker is this screen's one header control. A
   * route that kept drawing its own `PageHeader` above this one would put two `<h1>`s
   * on the home page.
   */
  it('draws its own header, with the tabs and the period under it', () => {
    renderPage()
    expect(screen.getByRole('heading', { level: 1, name: 'Home' })).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(screen.getByRole('tab', { name: 'Commerciale' })).toBeInTheDocument()
    expect(screen.getByLabelText('Dal')).toBeInTheDocument()
  })
})

describe('DashboardPage, two tabs', () => {
  it('offers exactly the commercial and economic tabs, and marks the current one', () => {
    renderPage({ ...SEARCH, tab: 'economica' })
    const tabs = screen.getAllByRole('tab').map((tab) => tab.textContent)
    expect(tabs).toEqual(['Commerciale', 'Economica'])
    expect(screen.getByRole('tab', { name: 'Economica' })).toHaveAttribute('aria-selected', 'true')
  })

  it('shows the period picker on both tabs', () => {
    renderPage({ ...SEARCH, tab: 'economica' })
    expect(screen.getByLabelText('Dal')).toBeInTheDocument()
  })
})
