import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import type { components } from '@/lib/api-types'

export type GmailHealth = components['schemas']['GmailHealth']
export type GoogleAccountRead = components['schemas']['GoogleAccountRead']
export type GmailMessageRead = components['schemas']['GmailMessageRead']
export type SyncReport = components['schemas']['SyncReport']

export type GmailEntityType = 'customer' | 'person' | 'deal'

/**
 * Keyed locally rather than in `lib/query.ts`'s central `queryKeys`, which is where
 * every other feature's keys live. The prefix matters more than the location here:
 * `['gmail', 'messages', ...]` lets a sync invalidate every entity's Email tab at once
 * without enumerating which customers happen to be cached, and that only works if the
 * two keys share a root nobody else writes under.
 */
export const gmailKeys = {
  health: ['gmail', 'health'] as const,
  messages: (entityType: string, entityId: string) =>
    ['gmail', 'messages', entityType, entityId] as const,
}

/**
 * `GET /api/gmail/account` answers 200 even on an installation with no Google client
 * (see the router's own docstring), so this query is in `isError` only when the request
 * genuinely failed. "Gmail non è configurato" arrives as data -- `configured: false` --
 * and is a screen, not an error.
 */
export function useGmailHealth() {
  return useQuery({
    queryKey: gmailKeys.health,
    queryFn: () => unwrap(api.GET('/api/gmail/account')),
  })
}

/**
 * Invalidates the health row *and* every stored-message list. A cycle moves
 * `last_sync_at`, and any entity's Email tab may have gained messages; which ones is
 * exactly what the client cannot know, so it invalidates the whole prefix.
 */
function invalidateAfterSync(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: gmailKeys.health })
  void queryClient.invalidateQueries({ queryKey: ['gmail', 'messages'] })
}

export function useSyncGmail() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/gmail/sync')),
    onSuccess: () => invalidateAfterSync(queryClient),
  })
}

export function useDisconnectGmail() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ eliminaMessaggi }: { eliminaMessaggi: boolean }) => {
      await unwrap(
        api.DELETE('/api/gmail/account', {
          params: { query: { elimina_messaggi: eliminaMessaggi } },
        }),
      )
    },
    // Both, even when the messages were kept: the account row's `status` changed, and
    // an Email tab rendered from a cache taken before the disconnect would show a
    // history the panel now says is gone.
    onSuccess: () => invalidateAfterSync(queryClient),
  })
}

export function useSetStoreBodies() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (enabled: boolean) =>
      unwrap(api.PATCH('/api/gmail/account', { body: { gmail_store_bodies: enabled } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: gmailKeys.health }),
  })
}

/**
 * The stored mirror for one entity. No `enabled: !!id` escape hatch: the id is a
 * required route param at every call site, so there is no empty-string spelling to get
 * wrong.
 */
export function useGmailMessages(args: { entityType: GmailEntityType; entityId: string }) {
  return useQuery({
    queryKey: gmailKeys.messages(args.entityType, args.entityId),
    queryFn: () =>
      unwrap(
        api.GET('/api/gmail/messages', {
          params: { query: { entity_type: args.entityType, entity_id: args.entityId } },
        }),
      ),
  })
}
