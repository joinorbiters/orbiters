import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import type { components } from '@/lib/api-types'
import { queryKeys } from '@/lib/query'

/**
 * Wire shape of one deal and one pipeline stage, taken directly from the generated
 * OpenAPI schema rather than hand-declared -- the same reasoning as `Customer`/
 * `Person`'s own aliases (features/customers/queries.ts, features/people/
 * queries.ts): the single source of truth is `DealRead`/`PipelineStageRead` in
 * packages/core/src/pigrocrm/core/{deals,pipeline}/schemas.py, and these track it
 * through `pnpm generate:api` automatically.
 *
 * Note `valore_previsto`/`ore_preventivate`/`valore_preventivato` come through as
 * `string | null`, never `number`: `Decimal` fields serialise to JSON strings
 * (confirmed against the generated type), which is exactly what lets `columns.tsx`
 * parse them digit-by-digit instead of through a binary float -- see that file's
 * `centsFromDecimalString` for why that distinction matters the moment more than
 * one of these is added together.
 */
export type Deal = components['schemas']['DealRead']
export type Stage = components['schemas']['PipelineStageRead']

type DealCreateBody = components['schemas']['DealCreate']
type DealUpdateBody = components['schemas']['DealUpdate']

interface DealsListParams {
  search?: string
  customer_id?: string
  stage_id?: string
}

/**
 * The aggregated result `useDeals` resolves to -- deliberately not the wire's own
 * `DealPage` (`{items, next_cursor}`): that shape is one *page*, and handing it
 * straight to the Kanban board is exactly the bug this type exists to rule out.
 * See `fetchAllDeals` below for the full reasoning.
 */
export interface DealsResult {
  items: Deal[]
  /** True only if `MAX_PAGES` was exhausted while the server still reported more
   *  (`next_cursor` still non-null) -- see `fetchAllDeals`'s own docstring. Never
   *  true for any tenant this product is actually sized for; it exists so a
   *  pathological one is told, not silently shown a partial board. */
  truncated: boolean
}

// `DealListQuery.limit` (deals/schemas.py) is bounded `ge=1, le=200`; 200 is
// therefore the fewest possible requests to drain a real result set.
const MAX_PAGE_SIZE = 200
// A hard stop against a runaway loop, not a bound this product's own target user
// (a solo/small-team Italian freelancer) is expected to ever approach: 100 pages
// of 200 is 20,000 deals. If a tenant ever does cross it, `truncated: true` says
// so explicitly instead of either looping indefinitely or silently stopping.
const MAX_PAGES = 100

/**
 * `GET /api/deals` is cursor-paginated and bounded (`limit` defaults to 50, capped
 * at 200 -- deals/schemas.py's `DealListQuery`, deals/repository.py's keyset
 * pagination on `Deal.id` ascending). A `useDeals` that only ever fetched the
 * first page -- what the brief's own sample did -- silently renders a subset of
 * a stage's deals the moment a tenant passes 50 open deals: the Kanban's own
 * per-column count and total (`columns.tsx`'s `sumValorePrevisto`) would then be
 * wrong with nothing on screen saying so, which is worse than a visible cap.
 *
 * This walks the cursor at the maximum page size until the server reports no
 * `next_cursor`, aggregating every page into one flat list -- "every deal
 * matching the filter" is the actual contract the Kanban and the list view both
 * need, not "the first 50". `MAX_PAGES` is the one safety valve: see its own
 * comment for why crossing it is surfaced rather than silent.
 */
export async function fetchAllDeals(params: DealsListParams): Promise<DealsResult> {
  const items: Deal[] = []
  let cursor: string | undefined
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const data = await unwrap(
      api.GET('/api/deals', {
        params: { query: { ...params, limit: MAX_PAGE_SIZE, cursor } },
      }),
    )
    items.push(...data.items)
    if (!data.next_cursor) return { items, truncated: false }
    cursor = data.next_cursor
  }
  return { items, truncated: true }
}

export function useDeals(params: DealsListParams = {}) {
  return useQuery({
    queryKey: queryKeys.deals(params),
    queryFn: () => fetchAllDeals(params),
  })
}

export function useStages() {
  return useQuery({
    queryKey: queryKeys.stages,
    queryFn: () => unwrap(api.GET('/api/pipeline-stages')),
  })
}

export function useDeal(dealId: string) {
  return useQuery({
    queryKey: queryKeys.deal(dealId),
    queryFn: () =>
      unwrap(api.GET('/api/deals/{deal_id}', { params: { path: { deal_id: dealId } } })),
  })
}

/**
 * `body` arrives as the loosely-typed `Record<string, unknown>` that
 * `DealForm.submit` builds -- the same idiom `customers/queries.ts`/`people/
 * queries.ts` use for the identical reason: a dynamic mix of native columns and
 * tenant-defined custom fields no fixed interface can describe. `as unknown as
 * DealCreateBody` says so honestly rather than a bare `as never` that hides the
 * target type entirely.
 */
export function useCreateDeal() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(api.POST('/api/deals', { body: body as unknown as DealCreateBody })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.deals() }),
  })
}

export function useUpdateDeal(dealId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(
        api.PATCH('/api/deals/{deal_id}', {
          params: { path: { deal_id: dealId } },
          body: body as unknown as DealUpdateBody,
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.deal(dealId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.deals() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.timeline('deal', dealId) })
    },
  })
}

/**
 * Optimistic: dragging a card and then watching a spinner is exactly the kind of
 * friction that makes a CRM unpleasant, so the move is written into every cached
 * deals list immediately, before the server has agreed to it.
 *
 * On failure the rollback has to actually restore the *previous* cache contents,
 * not merely re-render -- `onError` below puts every snapshotted query back
 * exactly as it was, which is what makes the dropped card visually snap back to
 * its original column once React re-renders from the restored data (`KanbanBoard`
 * re-derives each column by filtering on `pipeline_stage_id`, so restoring that
 * one field is enough). The server's own message still has to reach the user
 * separately -- this hook only manages the cache; the caller's `onError` is what
 * shows it (see routes/app/deal/index.tsx's `onMove`, which toasts
 * `toProblem(error).detail`). Verified live against the running API by soft-
 * deleting a deal in a second tab and then dragging its still-cached card in the
 * first: the PATCH 404s (`DealRepository.get` excludes a soft-deleted row, so
 * `move_stage` raises `NotFound`), the card returns to its original column, and a
 * toast reads "deal <id> not found" -- see task-8-report.md for the full
 * transcript.
 *
 * `getQueriesData`/`setQueryData` are typed as `DealsResult` for this hook's own
 * purposes, but the same `['deals', ...]` key prefix also matches `features/
 * customers/queries.ts`'s `useCustomerDeals` (a plain wire `DealPage`). Both
 * shapes carry `.items: Deal[]`, which is all this hook ever reads or rewrites,
 * so touching that cache entry too is harmless -- and `onSettled`'s invalidation
 * below refreshes it correctly regardless.
 */
export function useMoveDeal() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ dealId, stageId }: { dealId: string; stageId: string }) =>
      unwrap(
        api.PATCH('/api/deals/{deal_id}/stage', {
          params: { path: { deal_id: dealId } },
          body: { stage_id: stageId },
        }),
      ),
    onMutate: async ({ dealId, stageId }) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.deals() })
      const snapshot = queryClient.getQueriesData<DealsResult>({ queryKey: queryKeys.deals() })
      for (const [key, data] of snapshot) {
        if (!data) continue
        queryClient.setQueryData<DealsResult>(key, {
          ...data,
          items: data.items.map((deal) =>
            deal.id === dealId ? { ...deal, pipeline_stage_id: stageId } : deal,
          ),
        })
      }
      return { snapshot }
    },
    onError: (_error, _variables, context) => {
      for (const [key, data] of context?.snapshot ?? []) {
        queryClient.setQueryData(key, data)
      }
    },
    onSettled: (_data, _error, variables) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.deals() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.deal(variables.dealId) })
    },
  })
}

/**
 * `DELETE /api/deals/{id}` is a soft delete: the server sets `deleted_at`. Unlike
 * `CustomerService.soft_delete`, `DealService.soft_delete` raises no conflict --
 * nothing else in this slice holds a foreign key to a deal -- so there is no
 * active-dependents count to surface here.
 */
export function useDeleteDeal() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (dealId: string) =>
      unwrap(api.DELETE('/api/deals/{deal_id}', { params: { path: { deal_id: dealId } } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.deals() }),
  })
}
