import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import type { components } from '@/lib/api-types'

export type SollecitoCandidate = components['schemas']['SollecitoCandidate']
export type PaymentReminderRead = components['schemas']['PaymentReminderRead']
/** Renamed on the way in. The generated schema calls the page `SollecitiPage`, which is
 *  also the name of the screen in this folder; one of the two has to give, and a type is
 *  cheaper to rename than a component somebody navigates to. */
export type SollecitiCandidatesPage = components['schemas']['SollecitiPage']

export const sollecitiKeys = {
  candidates: ['payment-reminders', 'candidates'] as const,
}

/**
 * Every invoice worth chasing, worst first and repliers last.
 *
 * The order comes from the server and is not re-derived here. "A client who has replied
 * goes last" is a judgement about how to chase money, and a second copy of it in the
 * browser is how the list a person sees and the list the API believes in start
 * disagreeing -- which is the whole family of defect this slice exists to remove.
 *
 * A plain read of this installation's own register: no Google call, no Gmail quota, and
 * it works with the mailbox disconnected -- `ultima_risposta_il` is then `null`, which
 * says «we do not know», not «nobody replied».
 */
export function useCandidates() {
  return useQuery({
    queryKey: sollecitiKeys.candidates,
    queryFn: () => unwrap(api.GET('/api/payment-reminders/candidates')),
  })
}

/**
 * Prepares one reminder. **It sends nothing** (spec 8.3): it writes the
 * `payment_reminders` row and its draft, and hands back the draft's id. The draft leaves
 * through `/api/email-drafts/{id}/send` like any other email -- one send path in the
 * whole slice, and a second one here is exactly where a double send would come back.
 *
 * Invalidates the candidate list, because preparing a reminder takes the invoice off it:
 * a row that stayed would offer a button the API now refuses, for
 * `solleciti_min_interval_days`. And the draft lists, because the Email tab of that
 * customer has just gained an unsent draft.
 */
export function useCreateReminder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (invoiceId: string) =>
      unwrap(api.POST('/api/payment-reminders', { body: { invoice_id: invoiceId } })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: sollecitiKeys.candidates })
      void queryClient.invalidateQueries({ queryKey: ['email-drafts', 'entity'] })
    },
  })
}
