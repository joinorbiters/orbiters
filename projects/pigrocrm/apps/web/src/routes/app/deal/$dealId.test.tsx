import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DealDetail } from './$dealId'
import { api } from '@/lib/api'

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return { ...actual, useParams: () => ({ dealId: 'd1' }), useNavigate: () => vi.fn() }
})

vi.mock('@/lib/auth', () => ({ useCanWrite: () => false }))

// `api.GET` is spied on directly, mirroring `clienti/$customerId.test.tsx`: what
// is under test is this route's own handling of what the real `unwrap` produces,
// not a reimplementation of it. `DealDetail` also mounts `useEntitySchema` and
// `useStages` unconditionally -- both resolve to a harmless empty success below,
// since neither is ever read before the isError/404 guard under test here
// returns.
const mockGet = vi.spyOn(api, 'GET')

function ok(data: unknown) {
  return Promise.resolve({ data, response: new Response(null, { status: 200 }) }) as never
}
function failed(error: unknown, status: number) {
  return Promise.resolve({ error, response: new Response(null, { status }) }) as never
}

function mockDealFetch(result: ReturnType<typeof ok> | ReturnType<typeof failed>) {
  mockGet.mockImplementation(
    ((path: string) => (path === '/api/deals/{deal_id}' ? result : ok({ items: [] }))) as never,
  )
}

beforeEach(() => {
  mockGet.mockReset()
})

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('DealDetail', () => {
  it('shows "Deal non trovato" for a genuine 404', async () => {
    mockDealFetch(
      failed(
        { type: 'about:blank', title: 'Non trovato', status: 404, detail: 'deal non trovato', code: 'not_found' },
        404,
      ),
    )
    renderWithClient(<DealDetail />)
    expect(await screen.findByText('Deal non trovato.')).toBeInTheDocument()
  })

  /**
   * The bug this guards against: before this fix, `if (!deal) return <p>Deal
   * non trovato.</p>` fired for *any* failed fetch, not only a real 404 -- a
   * 500, a 502 or a dropped connection told the user the record does not
   * exist. This reuses `QueryErrorBanner`, the same surface `DataTable` and
   * `Timeline` already show for a failed request everywhere else in this app,
   * rather than inventing a fourth way to say "something went wrong".
   */
  it('shows the failed-request banner, not "Deal non trovato", when the fetch fails for a reason other than 404', async () => {
    mockDealFetch(failed({ code: 'http_error', detail: 'Il server non risponde.', status: 503 }, 503))
    renderWithClient(<DealDetail />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Il server non risponde.')
    expect(screen.queryByText('Deal non trovato.')).not.toBeInTheDocument()
  })
})
