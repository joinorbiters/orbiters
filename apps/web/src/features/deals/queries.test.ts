import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchAllDeals } from './queries'
import type { Deal } from './queries'
import { api } from '@/lib/api'

const mockGet = vi.spyOn(api, 'GET')

beforeEach(() => {
  mockGet.mockReset()
})

function page(items: Partial<Deal>[], nextCursor: string | null) {
  return Promise.resolve({
    data: { items, next_cursor: nextCursor },
    response: new Response(null, { status: 200 }),
  })
}

function deal(id: string): Partial<Deal> {
  return { id, nome: `Deal ${id}`, pipeline_stage_id: 's1' }
}

describe('fetchAllDeals', () => {
  it('resolves in one request when the first page already has no next_cursor', async () => {
    mockGet.mockReturnValueOnce(page([deal('a'), deal('b')], null))

    const result = await fetchAllDeals({})

    expect(result).toEqual({ items: [deal('a'), deal('b')], truncated: false })
    expect(mockGet).toHaveBeenCalledTimes(1)
  })

  /**
   * The exact bug this function exists to fix: `GET /api/deals` defaults to 50
   * results per page and caps at 200 (`DealListQuery.limit`, deals/schemas.py).
   * A `useDeals` that stopped at the first page -- what the brief's own sample
   * did -- would silently drop every deal past the first page. This proves the
   * aggregation actually walks the cursor rather than trusting a single
   * response.
   */
  it('walks every page until next_cursor is null, concatenating all of them', async () => {
    mockGet
      .mockReturnValueOnce(page([deal('a'), deal('b')], 'b'))
      .mockReturnValueOnce(page([deal('c')], 'c'))
      .mockReturnValueOnce(page([deal('d')], null))

    const result = await fetchAllDeals({})

    expect(result.items.map((d) => d.id)).toEqual(['a', 'b', 'c', 'd'])
    expect(result.truncated).toBe(false)
    expect(mockGet).toHaveBeenCalledTimes(3)
  })

  it('requests the maximum page size on every page, not the server default', async () => {
    mockGet.mockReturnValueOnce(page([], null))

    await fetchAllDeals({})

    expect(mockGet).toHaveBeenCalledWith(
      '/api/deals',
      expect.objectContaining({ params: expect.objectContaining({ query: expect.objectContaining({ limit: 200 }) }) }),
    )
  })

  it('forwards the cursor from one page as the next request’s cursor', async () => {
    mockGet.mockReturnValueOnce(page([deal('a')], 'a')).mockReturnValueOnce(page([deal('b')], null))

    await fetchAllDeals({})

    const secondCallArgs = mockGet.mock.calls[1]
    expect(secondCallArgs?.[1]).toEqual(
      expect.objectContaining({ params: expect.objectContaining({ query: expect.objectContaining({ cursor: 'a' }) }) }),
    )
  })

  it('forwards search/customer_id/stage_id filters unchanged on every page', async () => {
    mockGet.mockReturnValueOnce(page([], null))

    await fetchAllDeals({ search: 'sito', customer_id: 'cust-1', stage_id: 'stage-1' })

    expect(mockGet).toHaveBeenCalledWith(
      '/api/deals',
      expect.objectContaining({
        params: expect.objectContaining({
          query: expect.objectContaining({
            search: 'sito',
            customer_id: 'cust-1',
            stage_id: 'stage-1',
          }),
        }),
      }),
    )
  })

  /**
   * The one safety valve: a tenant so large it never runs out of `next_cursor`
   * within `MAX_PAGES` gets `truncated: true` instead of looping forever, or
   * worse, silently stopping with no way for the caller to know. Not a state
   * this product's own target user is expected to reach -- see the constant's
   * own comment in queries.ts -- but if it ever happens, this is what the UI's
   * truncation banner (routes/app/deal/index.tsx, routes/app/deal/lista.tsx)
   * keys off.
   */
  it('reports truncated and stops after the page cap, never looping indefinitely', async () => {
    // Every page claims there is more -- if the loop had no cap, this would
    // hang the test (and the real app) forever.
    mockGet.mockImplementation(() => page([deal('x')], 'always-more'))

    const result = await fetchAllDeals({})

    expect(result.truncated).toBe(true)
    expect(mockGet).toHaveBeenCalledTimes(100)
    expect(result.items).toHaveLength(100)
  })
})
