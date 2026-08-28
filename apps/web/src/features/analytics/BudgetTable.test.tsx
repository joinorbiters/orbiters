import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { BudgetTable } from './BudgetTable'

// See `EconomicsTab.test.tsx` for why the module is mocked rather than the network: the
// brief's `msw` is not a dependency here and could not have intercepted an openapi-fetch
// client that captured `fetch` at import time.
vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { GET: vi.fn() } }
})

const DEAL = 'aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa'

const row = (overrides: Record<string, unknown> = {}) => ({
  deal_id: DEAL,
  nome: 'Progetto Alfa',
  ore_preventivate: '100.00',
  ore_consuntivate: '40.00',
  valore_preventivato: '10000.00',
  ricavi: '4000.00',
  avanzamento_ore: '40.00',
  budget_pro_rata: '4000.00',
  scostamento_valore: '0.00',
  scostamento_ore: '-60.00',
  tariffa_media_preventivata: '100.00',
  tariffa_media_consuntivata: '100.00',
  non_preventivato: false,
  pro_rata_non_calcolabile: false,
  ...overrides,
})

const page = (overrides: Record<string, unknown> = {}) => ({
  items: [row()],
  next_cursor: null,
  totale_preventivato: '10000.00',
  totale_ricavi: '4000.00',
  deal_preventivati: 1,
  deal_non_preventivati: 0,
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
      <BudgetTable />
    </QueryClientProvider>,
  )
}

/** The one data row, found by its deal name rather than by index, so a header row or a
 *  totals row appearing later does not silently move the assertion onto it. */
async function dealRow(nome = 'Progetto Alfa') {
  return (await screen.findByText(nome)).closest('tr') as HTMLElement
}

beforeEach(() => {
  vi.mocked(api.GET).mockReset()
})

describe('BudgetTable', () => {
  it('shows the full budget and the pro-rata side by side', async () => {
    vi.mocked(api.GET).mockImplementation(() => ok(page()))
    renderTable()

    // The full budget is shown *beside* the pro-rata, never instead of it: a deal 40%
    // through its hours has spent 4.000 of a 10.000 budget, and only one of those two
    // numbers answers "is it on track?" while only the other answers "what did we sell?".
    expect(await screen.findByText('Preventivo pieno')).toBeInTheDocument()
    expect(screen.getByText('Preventivo pro-rata')).toBeInTheDocument()

    // Whitespace normalised the way testing-library's own text matchers do it: ICU puts
    // a NO-BREAK SPACE before the € sign, and pinning that code point into the expected
    // strings would make this test about ICU's spacing rather than about the columns.
    const cells = within(await dealRow()).getAllByRole('cell')
    expect(cells.map((cell) => (cell.textContent ?? '').replace(/\s+/g, ' '))).toEqual([
      'Progetto Alfa',
      '100 / 40',
      '40,00 %',
      '10.000,00 €',
      '4.000,00 €',
      '4.000,00 €',
      '0,00 €',
      '100,00 € / 100,00 €',
    ])
  })

  it('says "non preventivato" instead of showing a 100% overrun', async () => {
    vi.mocked(api.GET).mockImplementation(() =>
      ok(
        page({
          items: [
            row({
              ore_preventivate: null,
              valore_preventivato: null,
              avanzamento_ore: null,
              budget_pro_rata: null,
              scostamento_valore: null,
              scostamento_ore: null,
              tariffa_media_preventivata: null,
              non_preventivato: true,
            }),
          ],
          totale_preventivato: '0.00',
          totale_ricavi: '0.00',
          deal_preventivati: 0,
          deal_non_preventivati: 1,
        }),
      ),
    )
    renderTable()

    // A deal nobody estimated has not overrun its estimate by everything: it has no
    // estimate, which is a different thing to tell somebody and a different thing to do
    // about it.
    expect(await screen.findByText(/non preventivato/i)).toBeInTheDocument()
    expect(screen.queryByText('100,00 %')).not.toBeInTheDocument()
    expect(screen.getByText(/1 deal senza preventivo/i)).toBeInTheDocument()
  })

  it('says nothing about unbudgeted deals when every deal has an estimate', async () => {
    vi.mocked(api.GET).mockImplementation(() => ok(page()))
    renderTable()

    await dealRow()
    expect(screen.queryByText(/senza preventivo/i)).not.toBeInTheDocument()
  })

  /** A budgeted deal whose *hours* were never estimated can still be compared on value,
   *  but its pro-rata share has no percentage to be a share of. The cell says so instead
   *  of falling back to the full budget, which would read as a deal exactly on track. */
  it('marks a row whose pro-rata cannot be computed', async () => {
    vi.mocked(api.GET).mockImplementation(() =>
      ok(
        page({
          items: [
            row({
              ore_preventivate: null,
              avanzamento_ore: null,
              budget_pro_rata: null,
              scostamento_valore: null,
              pro_rata_non_calcolabile: true,
            }),
          ],
        }),
      ),
    )
    renderTable()

    expect(await screen.findByText(/pro-rata non calcolabile/i)).toBeInTheDocument()
    // The full budget is still there: it is known, and it is what the row can be read on.
    expect(within(await dealRow()).getByText('10.000,00 €')).toBeInTheDocument()
  })

  it('renders a banner, never an empty table, when the request fails', async () => {
    vi.mocked(api.GET).mockImplementation(() => failed({ detail: 'Boom' }, 500))
    renderTable()

    expect(await screen.findByRole('alert')).toHaveTextContent('Boom')
    expect(screen.queryByText(/nessun deal/i)).not.toBeInTheDocument()
  })

  it('asks for the current month, built from local date parts', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2026, 1, 17))
    vi.mocked(api.GET).mockImplementation(() => ok(page()))
    renderTable()

    await waitFor(() => expect(api.GET).toHaveBeenCalled())
    const [path, options] = vi.mocked(api.GET).mock.calls[0] as unknown as [
      string,
      { params: { query: Record<string, unknown> } },
    ]
    expect(path).toBe('/api/analytics/budget')
    // February 2026 ends on the 28th: the window is the month, not a fixed 30 days.
    expect(options.params.query).toMatchObject({ from: '2026-02-01', to: '2026-02-28' })
    vi.useRealTimers()
  })

  it('asks again for the window the picker was moved to', async () => {
    vi.mocked(api.GET).mockImplementation(() => ok(page()))
    renderTable()
    await dealRow()

    fireEvent.change(screen.getByLabelText('Da'), { target: { value: '2026-01' } })
    fireEvent.change(screen.getByLabelText('A'), { target: { value: '2026-03' } })

    await waitFor(() => {
      const last = vi.mocked(api.GET).mock.calls.at(-1) as unknown as [
        string,
        { params: { query: Record<string, unknown> } },
      ]
      // March 2026 ends on the 31st, and the last day of the *to* month is included:
      // a report that stopped on the 1st would drop a month of invoices.
      expect(last[1].params.query).toMatchObject({ from: '2026-01-01', to: '2026-03-31' })
    })
  })
})
