import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // A 401 means the session expired; retrying just delays the redirect. A 403
      // means the actor's role will not change mid-request either. Both are terminal
      // for this request -- everything else gets the library's usual couple of
      // retries for a transient blip.
      retry: (failureCount, error) => {
        const status = (error as { status?: number }).status
        if (status === 401 || status === 403) return false
        return failureCount < 2
      },
    },
  },
})

export const queryKeys = {
  me: ['me'] as const,
  customers: (params?: unknown) => ['customers', params ?? {}] as const,
  customer: (id: string) => ['customer', id] as const,
  people: (params?: unknown) => ['people', params ?? {}] as const,
  person: (id: string) => ['person', id] as const,
  deals: (params?: unknown) => ['deals', params ?? {}] as const,
  deal: (id: string) => ['deal', id] as const,
  timeline: (entity: string, id: string) => ['timeline', entity, id] as const,
  fields: (entityType: string) => ['field-definitions', entityType] as const,
  schema: (entityType: string) => ['schema', entityType] as const,
  stages: ['pipeline-stages'] as const,
  users: ['users'] as const,
  // Scoped by user id, not a bare `['tokens']`: `GET /api/tokens` already
  // scopes the *response* to the caller (`PatService.list` filters on
  // `actor.id`), and `logout()`'s `queryClient.clear()` already wipes this
  // cache before another user's session could read it either way -- but a
  // per-user key is what makes a stale cross-user read impossible by
  // construction, rather than merely unreproduced today.
  tokens: (userId: string) => ['tokens', userId] as const,
  // `owner` is the discriminated `{customerId} | {dealId}` object, so a customer's
  // documents and a deal's documents can never share a cache entry, and
  // `invalidateQueries({queryKey: ['documents']})` still matches both.
  documents: (owner?: unknown) => ['documents', owner ?? {}] as const,
  document: (id: string) => ['document', id] as const,
  documentVersions: (id: string) => ['document-versions', id] as const,
  templates: () => ['templates'] as const,
  templateDescription: (id: string) => ['template-description', id] as const,
  emitter: ['emitter'] as const,
}
