import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import type { components } from '@/lib/api-types'
import { gmailKeys, type GmailEntityType } from './queries'

export type EmailDraftRead = components['schemas']['EmailDraftRead']
export type EmailDraftCreate = components['schemas']['EmailDraftCreate']
export type EmailDraftUpdate = components['schemas']['EmailDraftUpdate']
export type EmailDraftPage = components['schemas']['EmailDraftPage']
export type SendState = EmailDraftRead['send_state']

/**
 * The states in which the text is still the user's -- and therefore, necessarily, the
 * states from which it can be sent. One set and not two, exactly as
 * `EDITABLE_SEND_STATES` in `packages/core/src/pigrocrm/core/gmail/schemas.py`: "you may
 * edit this" and "you may send this" are the same claim about a draft that has not left,
 * and two lists drifting apart would offer a Send button the API refuses, or refuse one
 * it would have accepted.
 *
 * `fallito` is in it on purpose (spec 6.3(a)): a refused send leaves the draft intact
 * with the error beside it, and the composer reopens with the text inside. A draft frozen
 * by its own failure would leave "write it again" as the only recovery, which is the loss
 * the `email_drafts` table exists to prevent.
 */
export const EDITABLE_SEND_STATES: readonly SendState[] = ['bozza', 'fallito']

export function isEditable(state: SendState | undefined): boolean {
  return state !== undefined && EDITABLE_SEND_STATES.includes(state)
}

/**
 * Keyed locally, under the same rule `gmailKeys` states: the prefix matters more than
 * the location. `['email-drafts', ...]` is a root nobody else writes under, so a send can
 * invalidate one draft without guessing which entity lists happen to be cached.
 */
export const draftKeys = {
  all: ['email-drafts'] as const,
  one: (draftId: string) => ['email-drafts', 'one', draftId] as const,
  forEntity: (entityType: string, entityId: string) =>
    ['email-drafts', 'entity', entityType, entityId] as const,
}

/**
 * One draft. `enabled` rather than a conditional call -- a hook cannot be called
 * conditionally, and the composer legitimately runs with no draft at all while somebody
 * is still typing the first one (see `EmailComposer`: the row is created on the first
 * save, not on the first keystroke, so that opening the composer and closing it again
 * leaves nothing behind).
 */
export function useDraft(draftId: string | undefined) {
  return useQuery({
    enabled: draftId !== undefined && draftId !== '',
    queryKey: draftKeys.one(draftId ?? ''),
    queryFn: () =>
      unwrap(
        api.GET('/api/email-drafts/{draft_id}', {
          params: { path: { draft_id: draftId ?? '' } },
        }),
      ),
  })
}

/** Every draft filed against one entity, newest first. What the Email tab reads to show
 *  «una bozza non ancora inviata» next to the correspondence that has left. */
export function useDraftsForEntity(args: { entityType: GmailEntityType; entityId: string }) {
  return useQuery({
    queryKey: draftKeys.forEntity(args.entityType, args.entityId),
    queryFn: () =>
      unwrap(
        api.GET('/api/email-drafts', {
          params: { query: { entity_type: args.entityType, entity_id: args.entityId } },
        }),
      ),
  })
}

/**
 * Invalidates one draft and every entity list. Both, always: a draft's own row changed,
 * and the tab that lists «bozze non inviate» is keyed by entity rather than by draft, so
 * which list to touch is exactly what the client cannot know.
 */
function invalidateDraft(queryClient: ReturnType<typeof useQueryClient>, draftId: string) {
  void queryClient.invalidateQueries({ queryKey: draftKeys.one(draftId) })
  void queryClient.invalidateQueries({ queryKey: ['email-drafts', 'entity'] })
}

export function useCreateDraft() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: EmailDraftCreate) => unwrap(api.POST('/api/email-drafts', { body })),
    onSuccess: (draft) => invalidateDraft(queryClient, draft.id),
  })
}

export function useUpdateDraft() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: EmailDraftUpdate }) =>
      unwrap(
        api.PATCH('/api/email-drafts/{draft_id}', {
          params: { path: { draft_id: id } },
          body: patch,
        }),
      ),
    onSuccess: (draft) => invalidateDraft(queryClient, draft.id),
  })
}

export function useDeleteDraft() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (draftId: string) => {
      await unwrap(
        api.DELETE('/api/email-drafts/{draft_id}', {
          params: { path: { draft_id: draftId } },
        }),
      )
      return draftId
    },
    onSuccess: (draftId) => invalidateDraft(queryClient, draftId),
  })
}

/**
 * The one call in the system with no idempotency key.
 *
 * No `retry`, and there must never be one: Gmail offers no idempotency key, so a second
 * attempt is a second email in somebody's client's inbox. React Query does not retry
 * mutations by default and this relies on that rather than restating it -- what it does
 * restate, in `EmailComposer`, is that a *user* cannot press it twice either.
 *
 * Invalidates the stored-message lists as well as the draft, because a successful send
 * writes an outbound `gmail_messages` row that the Email tab shows: without it the
 * message the user just sent is missing from the conversation they sent it in.
 */
export function useSendDraft() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (draftId: string) =>
      unwrap(
        api.POST('/api/email-drafts/{draft_id}/send', {
          params: { path: { draft_id: draftId } },
        }),
      ),
    onSuccess: (draft) => {
      invalidateDraft(queryClient, draft.id)
      void queryClient.invalidateQueries({ queryKey: ['gmail', 'messages'] })
    },
  })
}

/**
 * «Verifica»: resolves an unknown outcome by *asking Gmail*, never by sending again.
 *
 * It is a separate mutation from `useSendDraft` for the same reason it is a separate
 * endpoint. A "riprova" that re-posted the send would offer the recipient a second copy
 * of a message that may already be in their inbox, which is the exact defect `incerto`
 * exists to name.
 *
 * Invalidates the message lists too: a reconciliation that finds the message adopts it,
 * which writes the same outbound row a successful send would have.
 */
export function useReconcileDraft() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (draftId: string) =>
      unwrap(
        api.POST('/api/email-drafts/{draft_id}/reconcile', {
          params: { path: { draft_id: draftId } },
        }),
      ),
    onSuccess: (draft) => {
      invalidateDraft(queryClient, draft.id)
      void queryClient.invalidateQueries({
        queryKey: gmailKeys.messages(draft.entity_type, draft.entity_id),
      })
    },
  })
}
