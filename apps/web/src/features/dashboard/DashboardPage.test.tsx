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
  vi.mocked(api.GET).mockResolvedValue({
    data: EMPTY_DASHBOARD,
    response: new Response(null, { status: 200 }),
  } as never)
})

describe('DashboardPage', () => {
  it('renders the tab the URL names, not the first one', async () => {
    renderPage({ ...SEARCH, tab: 'economica' })
    expect(await screen.findByText(/dashboard economica arriva/i)).toBeInTheDocument()
    expect(screen.queryByText(/pipeline aperta/i)).not.toBeInTheDocument()
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

  it('explains why the two unbuilt tabs are empty instead of showing zeros', async () => {
    // §17: "cosa che l'utente capisce, a differenza di una scheda che mostra zeri."
    renderPage({ ...SEARCH, tab: 'operativa' })
    expect(await screen.findByText(/time tracking/i)).toBeInTheDocument()
    expect(screen.queryByText('0,00 €')).not.toBeInTheDocument()
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
