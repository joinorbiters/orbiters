import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import type { components } from '@/lib/api-types'
import { queryKeys } from '@/lib/query'

/**
 * Wire shapes taken from the generated OpenAPI schema, never hand-declared: the single
 * source of truth is `analytics/schemas.py` and `pnpm generate:api` tracks it.
 *
 * Every economic field on these types is a `string`, deliberately -- a `Numeric` column
 * serialises to JSON as digits, not as a float. Nothing in this feature adds, divides or
 * rounds one of them: §6 forbids an economic total being born in the browser, and
 * `lib/no-float-money.test.ts` fails the build if a module tries.
 */
export type DealPnl = components['schemas']['DealPnl']
export type PeriodPnl = components['schemas']['PeriodPnl']
export type PnlTotals = components['schemas']['PnlTotals']
export type BudgetVsActualRow = components['schemas']['BudgetVsActualRow']
export type BudgetPage = components['schemas']['BudgetPage']
export type FiscalEstimate = components['schemas']['FiscalEstimate']

export interface PeriodParams {
  from: string
  to: string
  customer_id?: string
}

export function useDealPnl(dealId: string) {
  return useQuery({
    queryKey: queryKeys.dealPnl(dealId),
    queryFn: () =>
      unwrap(api.GET('/api/deals/{deal_id}/pnl', { params: { path: { deal_id: dealId } } })),
  })
}

/**
 * One deal's row of the estimate-versus-actual report, served by the endpoint that
 * serves the list -- never recomputed here, which is how a detail page and a report
 * start showing different variances for the same deal.
 *
 * `da`/`a` rather than `from`/`to` as parameter names, because `from` reads as the
 * keyword; the wire names stay `from`/`to`, which is what the router declares.
 */
export function useDealBudget(dealId: string, da: string, a: string) {
  return useQuery({
    queryKey: queryKeys.dealBudget(dealId, da, a),
    queryFn: () =>
      unwrap(
        api.GET('/api/deals/{deal_id}/budget', {
          params: { path: { deal_id: dealId }, query: { from: da, to: a } },
        }),
      ),
  })
}

export function usePeriodPnl(params: PeriodParams) {
  return useQuery({
    queryKey: queryKeys.periodPnl(params),
    queryFn: () => unwrap(api.GET('/api/analytics/pnl', { params: { query: params } })),
  })
}

export function useBudget(params: PeriodParams & { limit?: number; cursor?: string }) {
  return useQuery({
    queryKey: queryKeys.budget(params),
    queryFn: () => unwrap(api.GET('/api/analytics/budget', { params: { query: params } })),
  })
}

export function useFiscalEstimate(anno: number) {
  return useQuery({
    queryKey: queryKeys.fiscalEstimate(anno),
    queryFn: () => unwrap(api.GET('/api/analytics/fiscale', { params: { query: { anno } } })),
  })
}

/**
 * Invalidates the P&L, the hours and the deal's timeline: binding hours to a draft
 * changes what is left to invoice, which all three screens report. A stale «Ore da
 * fatturare» next to a freshly created draft is the shape of bug that makes somebody
 * generate the same draft twice.
 */
export function useToInvoiceDraft(dealId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { entry_ids: string[]; raggruppa_per_mese: boolean }) =>
      unwrap(
        api.POST('/api/deals/{deal_id}/time-entries/to-invoice-draft', {
          params: { path: { deal_id: dealId } },
          body,
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.dealPnl(dealId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.dealTimeSummary(dealId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.timeEntries() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.timeline('deal', dealId) })
      // The draft itself is a new invoice: the deal's Fatture tab and the invoice list
      // are stale the moment this resolves.
      void queryClient.invalidateQueries({ queryKey: queryKeys.invoices() })
    },
  })
}
