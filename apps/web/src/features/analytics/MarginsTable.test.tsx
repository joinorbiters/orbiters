import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { MarginsTable } from './MarginsTable'

// See `EconomicsTab.test.tsx` for why the module is mocked rather than the network.
vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { GET: vi.fn() } }
})

const totals = (overrides: Record<string, unknown> = {}) => ({
  ricavi: '0.00',
  costi_diretti: '0.00',
  costo_lavoro: '0.00',
  margine_lordo: '0.00',
  margine_percentuale: null,
  deal: 0,
  ...overrides,
})

const periodPnl = (overrides: Record<string, unknown> = {}) => ({
  da: '2026-05-01',
  a: '2026-05-31',
  customer_id: null,
  chiusi: totals({
    ricavi: '10000.00',
    costo_lavoro: '1100.00',
    margine_lordo: '8900.00',
    margine_percentuale: '89.00',
    deal: 2,
  }),
  in_corso: totals({ costo_lavoro: '1100.00', margine_lordo: '-1100.00', deal: 1 }),
  spese_generali: '450.00',
  periodo_chiuso: false,
  voci_scritte_in_ritardo: 0,
  ...overrides,
})

function ok(data: unknown) {
  return Promise.resolve({ data, response: new Response(null, { status: 200 }) }) as never
}

function failed(error: unknown, status: number) {
  return Promise.resolve({ error, response: new Response(null, { status }) }) as never
}

function renderTable() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MarginsTable />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(api.GET).mockReset()
})

describe('MarginsTable', () => {
  it('asks for the current month, built from local date parts', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2026, 4, 17))
    vi.mocked(api.GET).mockImplementation(() => ok(periodPnl()))
    renderTable()

    await waitFor(() => expect(api.GET).toHaveBeenCalled())
    const [path, options] = vi.mocked(api.GET).mock.calls[0] as unknown as [
      string,
      { params: { query: Record<string, unknown> } },
    ]
    expect(path).toBe('/api/analytics/pnl')
    expect(options.params.query).toEqual({ from: '2026-05-01', to: '2026-05-31' })
    vi.useRealTimers()
  })

  it('shows the two columns with only the closed one marked reportable', async () => {
    vi.mocked(api.GET).mockImplementation(() => ok(periodPnl()))
    renderTable()

    const closed = await screen.findByRole('group', { name: /deal chiusi/i })
    const running = screen.getByRole('group', { name: /deal in corso/i })
    expect(within(closed).getByText('8.900,00 €')).toBeInTheDocument()
    expect(within(running).getByText('-1.100,00 €')).toBeInTheDocument()
    expect(within(closed).getByText(/dato riportabile/i)).toBeInTheDocument()
    expect(within(running).queryByText(/dato riportabile/i)).toBeNull()
    expect(screen.queryByText('7.800,00 €')).toBeNull()
  })

  /** A closed period is one whose hours can no longer be edited, so its figures have
   *  stopped moving. Saying which of the two a report is comes before reading any number
   *  off it. */
  it('says whether the period is closed', async () => {
    vi.mocked(api.GET).mockImplementation(() => ok(periodPnl({ periodo_chiuso: true })))
    renderTable()

    expect(await screen.findByText(/periodo chiuso/i)).toBeInTheDocument()
    expect(screen.queryByText(/periodo aperto/i)).toBeNull()
  })

  it('says so when the period is still open', async () => {
    vi.mocked(api.GET).mockImplementation(() => ok(periodPnl()))
    renderTable()

    expect(await screen.findByText(/periodo aperto/i)).toBeInTheDocument()
    expect(screen.queryByText(/periodo chiuso/i)).toBeNull()
  })

  /** Hours written after the window ended are the reason a report re-read next week can
   *  disagree with itself. The count is shown so that difference is expected rather than
   *  discovered. */
  it('counts the entries written after the period ended', async () => {
    vi.mocked(api.GET).mockImplementation(() => ok(periodPnl({ voci_scritte_in_ritardo: 3 })))
    renderTable()

    expect(
      await screen.findByText(/3 voci scritte dopo la fine del periodo/i),
    ).toBeInTheDocument()
  })

  it('says nothing about late entries when there are none', async () => {
    vi.mocked(api.GET).mockImplementation(() => ok(periodPnl()))
    renderTable()

    await screen.findByRole('group', { name: /deal chiusi/i })
    expect(screen.queryByText(/scritte dopo la fine del periodo/i)).toBeNull()
  })

  it('asks again for the window the picker was moved to', async () => {
    vi.mocked(api.GET).mockImplementation(() => ok(periodPnl()))
    renderTable()
    await screen.findByRole('group', { name: /deal chiusi/i })

    fireEvent.change(screen.getByLabelText('Da'), { target: { value: '2026-01' } })

    await waitFor(() => {
      const last = vi.mocked(api.GET).mock.calls.at(-1) as unknown as [
        string,
        { params: { query: Record<string, unknown> } },
      ]
      expect(last[1].params.query).toMatchObject({ from: '2026-01-01' })
    })
  })

  it('renders a banner and no columns when the request fails', async () => {
    vi.mocked(api.GET).mockImplementation(() => failed({ detail: 'Boom' }, 500))
    renderTable()

    expect(await screen.findByRole('alert')).toHaveTextContent('Boom')
    expect(screen.queryByRole('group', { name: /deal chiusi/i })).toBeNull()
  })
})
