import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { useInvoice, useInvoices } from './queries'

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

// `openapi-fetch`'s client captures `globalThis.fetch` into a closure once, at
// `createClient()` time (see its own source: `fetch: baseFetch = globalThis.fetch`)
// -- so stubbing `globalThis.fetch` from inside a test never intercepts a request
// made through the shared `api` client; it only ever hits the real network. Every
// other query-layer test in this codebase (features/documents/queries.test.tsx,
// features/deals/queries.test.tsx) spies on `api.GET`/`api.PATCH` directly for
// exactly this reason, and this file follows the same convention.
const mockGet = vi.spyOn(api, 'GET')

afterEach(() => {
  mockGet.mockReset()
})

function ok(data: unknown) {
  return Promise.resolve({ data, response: new Response(null, { status: 200 }) } as never)
}

describe('useInvoice', () => {
  it('does not fire a request for an empty id', async () => {
    // B1: `useCustomer('')` once produced a 307 to the *list* endpoint with an
    // absolute URL, bypassing even the Vite proxy. The guard is on the hook, and this
    // is the test the original fix never got.
    const { result } = renderHook(() => useInvoice(''), { wrapper })
    await waitFor(() => expect(result.current.fetchStatus).toBe('idle'))
    expect(result.current.isPending).toBe(true)
    expect(mockGet).not.toHaveBeenCalled()
  })

  it('fires for a real id', async () => {
    mockGet.mockReturnValueOnce(ok({ id: '0192f0aa-0000-7000-8000-000000000001' }))
    const { result } = renderHook(() => useInvoice('0192f0aa-0000-7000-8000-000000000001'), {
      wrapper,
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mockGet).toHaveBeenCalledWith(
      '/api/invoices/{invoice_id}',
      expect.objectContaining({
        params: { path: { invoice_id: '0192f0aa-0000-7000-8000-000000000001' } },
      }),
    )
  })
})

describe('useInvoices', () => {
  it('passes the filters through as query parameters', async () => {
    mockGet.mockReturnValueOnce(ok({ items: [], next_cursor: null }))
    const { result } = renderHook(() => useInvoices({ tipo: 'proforma', anno: 2026 }), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mockGet).toHaveBeenCalledWith(
      '/api/invoices',
      expect.objectContaining({ params: { query: { tipo: 'proforma', anno: 2026 } } }),
    )
  })
})
