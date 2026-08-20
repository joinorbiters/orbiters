import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { OFFER_TRANSITIONS, useDocument, useDocuments } from './queries'

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

// `openapi-fetch`'s client captures `globalThis.fetch` into a closure once, at
// `createClient()` time (see its own source: `fetch: baseFetch = globalThis.fetch`)
// -- so spying on `globalThis.fetch` from inside a test never intercepts a request
// made through the shared `api` client; it only ever hits the real network. Every
// other query-layer test in this codebase (features/deals/queries.test.tsx) spies on
// `api.GET`/`api.PATCH` directly for exactly this reason, and this file follows the
// same convention rather than repeating a mock that would silently do nothing.
const mockGet = vi.spyOn(api, 'GET')

afterEach(() => {
  mockGet.mockReset()
})

function ok(data: unknown) {
  return Promise.resolve({ data, response: new Response(null, { status: 200 }) } as never)
}

function failed(error: unknown, status: number) {
  return Promise.resolve({ error, response: new Response(null, { status }) } as never)
}

describe('useDocuments', () => {
  it('asks for the customer it was given', async () => {
    mockGet.mockReturnValueOnce(ok({ items: [], next_cursor: null }))
    renderHook(() => useDocuments({ customerId: 'c-1' }), { wrapper })
    await waitFor(() => expect(mockGet).toHaveBeenCalled())
    expect(mockGet).toHaveBeenCalledWith(
      '/api/documents',
      expect.objectContaining({ params: { query: { customer_id: 'c-1' } } }),
    )
  })

  it('asks for the deal it was given', async () => {
    mockGet.mockReturnValueOnce(ok({ items: [], next_cursor: null }))
    renderHook(() => useDocuments({ dealId: 'd-1' }), { wrapper })
    await waitFor(() => expect(mockGet).toHaveBeenCalled())
    expect(mockGet).toHaveBeenCalledWith(
      '/api/documents',
      expect.objectContaining({ params: { query: { deal_id: 'd-1' } } }),
    )
  })

  it('surfaces a failure as an error, never as an empty list', async () => {
    mockGet.mockReturnValueOnce(failed({ code: 'not_found', detail: 'Non trovato' }, 404))
    const { result } = renderHook(() => useDocuments({ customerId: 'c-1' }), { wrapper })
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.data).toBeUndefined()
  })
})

describe('useDocument', () => {
  it('never fires with an empty id', () => {
    // B1: `useCustomer('')` once produced a 307 to the *list* endpoint with an
    // absolute URL that bypassed Vite's proxy entirely. Disabling the query is the
    // structural fix; this test is what keeps a refactor from undoing it.
    const { result } = renderHook(() => useDocument(''), { wrapper })
    expect(mockGet).not.toHaveBeenCalled()
    expect(result.current.fetchStatus).toBe('idle')
  })
})

describe('OFFER_TRANSITIONS', () => {
  it('mirrors the backend state machine exactly', () => {
    // The table is the backend's own (documents/service.py OFFER_TRANSITIONS). The UI
    // reads it to decide which buttons to draw; it never re-decides the rule, and a
    // refused transition still comes back as the server's own 409 message.
    expect(OFFER_TRANSITIONS.bozza).toEqual(['inviata'])
    expect(OFFER_TRANSITIONS.inviata).toEqual(['accettata', 'rifiutata', 'bozza'])
    expect(OFFER_TRANSITIONS.accettata).toEqual([])
    expect(OFFER_TRANSITIONS.rifiutata).toEqual([])
  })
})
