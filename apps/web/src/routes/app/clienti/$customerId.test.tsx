import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CustomerDetail } from './$customerId'
import { api } from '@/lib/api'

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return { ...actual, useParams: () => ({ customerId: 'c1' }), useNavigate: () => vi.fn() }
})

vi.mock('@/lib/auth', () => ({ useCanWrite: () => false }))

// `api.GET` is spied on directly (not `vi.mock('@/lib/api', ...)`), mirroring
// Timeline.test.tsx: what is under test is this route's own handling of what the
// real `unwrap` produces (a resolved customer, a thrown `ProblemDetail`), not a
// reimplementation of either. `CustomerDetail` also mounts `useEntitySchema`,
// `useCustomerPeople` and `useCustomerDeals` unconditionally, through the same
// client -- every path other than the customer fetch itself below resolves to a
// harmless empty success, since none of it is ever read before the isError/404
// guard under test here returns.
const mockGet = vi.spyOn(api, 'GET')

function ok(data: unknown) {
  return Promise.resolve({ data, response: new Response(null, { status: 200 }) }) as never
}
function failed(error: unknown, status: number) {
  return Promise.resolve({ error, response: new Response(null, { status }) }) as never
}

function mockCustomerFetch(result: ReturnType<typeof ok> | ReturnType<typeof failed>) {
  mockGet.mockImplementation(
    ((path: string) => (path === '/api/customers/{customer_id}' ? result : ok({ items: [] }))) as never,
  )
}

beforeEach(() => {
  mockGet.mockReset()
})

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('CustomerDetail', () => {
  it('shows "Cliente non trovato" for a genuine 404', async () => {
    mockCustomerFetch(
      failed(
        {
          type: 'about:blank',
          title: 'Non trovato',
          status: 404,
          detail: 'cliente non trovato',
          code: 'not_found',
        },
        404,
      ),
    )
    renderWithClient(<CustomerDetail />)
    expect(await screen.findByText('Cliente non trovato.')).toBeInTheDocument()
  })

  /**
   * The bug this guards against: before this fix, `if (!customer) return <p>
   * Cliente non trovato.</p>` fired for *any* failed fetch, not only a real
   * 404 -- a 500, a 502 or a dropped connection told the user the record does
   * not exist. This reuses `QueryErrorBanner`, the same surface `DataTable` and
   * `Timeline` already show for a failed request everywhere else in this app,
   * rather than inventing a fourth way to say "something went wrong".
   */
  it('shows the failed-request banner, not "Cliente non trovato", when the fetch fails for a reason other than 404', async () => {
    mockCustomerFetch(failed({ code: 'http_error', detail: 'Il server non risponde.', status: 503 }, 503))
    renderWithClient(<CustomerDetail />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Il server non risponde.')
    expect(screen.queryByText('Cliente non trovato.')).not.toBeInTheDocument()
  })
})
