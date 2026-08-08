import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import type { components } from '@/lib/api-types'
import type { EntityType } from '@/lib/schema'
import { queryKeys } from '@/lib/query'

// -- Field definitions --------------------------------------------------------
//
// Every wire shape below is taken directly from the generated OpenAPI schema
// (`components['schemas'][...]`), the same reasoning `features/deals/queries.ts`/
// `features/customers/queries.ts` already document for their own aliases: the
// single source of truth is the Pydantic model in packages/core, and these track
// it through `pnpm generate:api` automatically.

export type FieldDefinitionRecord = components['schemas']['FieldDefinitionRead']
type FieldDefinitionCreateBody = components['schemas']['FieldDefinitionCreate']

/**
 * `include_archived: true`, always -- unlike `useEntitySchema` (lib/schema.ts),
 * which only ever needs the fields Customers/Persons/Deals currently render and
 * therefore excludes archived ones by design, this admin screen's whole job is to
 * also show what has been archived. Archiving is reversible (`POST .../unarchive`
 * exists and the stored JSONB values are never touched -- see
 * `FieldDefinitionService.archive`'s own docstring), so a list that only ever
 * shows the active half would make that reversibility invisible: nothing on
 * screen would tell an admin that "Segmento" still exists, just hidden, or give
 * them anywhere to click to bring it back. `FieldsPanel` renders every row this
 * returns with a status badge and the one action (archive/unarchive) each row's
 * own state allows, rather than filtering either half out.
 */
export function useFieldDefinitions(entityType: EntityType) {
  return useQuery({
    queryKey: queryKeys.fields(entityType),
    queryFn: () =>
      unwrap(
        api.GET('/api/field-definitions', {
          params: { query: { entity_type: entityType, include_archived: true } },
        }),
      ),
  })
}

/**
 * Every field-definition mutation below invalidates both this admin list *and*
 * `queryKeys.schema` -- the live document `useEntitySchema` (lib/schema.ts) reads
 * to decide what columns/inputs/detail rows Customers, Persons and Deals render.
 * That second invalidation is the entire point of this product's custom-field
 * system: a field created (or archived, or restored) here shows up -- or
 * disappears -- on those three screens immediately, with no reload. Keyed off the
 * response's own `entity_type` rather than a caller-supplied one, so a hook
 * cannot invalidate the wrong entity's schema by a caller's mistake.
 */
function invalidateFieldQueries(queryClient: QueryClient, entityType: string) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.fields(entityType) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.schema(entityType) })
}

export function useCreateFieldDefinition() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(
        api.POST('/api/field-definitions', { body: body as unknown as FieldDefinitionCreateBody }),
      ),
    onSuccess: (field) => invalidateFieldQueries(queryClient, field.entity_type),
  })
}

export function useArchiveFieldDefinition() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (fieldId: string) =>
      unwrap(
        api.POST('/api/field-definitions/{field_id}/archive', {
          params: { path: { field_id: fieldId } },
        }),
      ),
    onSuccess: (field) => invalidateFieldQueries(queryClient, field.entity_type),
  })
}

/**
 * Symmetric to `useArchiveFieldDefinition`, and exactly as important: without
 * this, archiving would be a one-way door in the UI even though the API and the
 * data model both treat it as reversible. See `FieldsPanel.tsx` for where this
 * is wired to a visible "Ripristina" action on every archived row.
 */
export function useUnarchiveFieldDefinition() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (fieldId: string) =>
      unwrap(
        api.POST('/api/field-definitions/{field_id}/unarchive', {
          params: { path: { field_id: fieldId } },
        }),
      ),
    onSuccess: (field) => invalidateFieldQueries(queryClient, field.entity_type),
  })
}

// -- Pipeline stages ------------------------------------------------------------
//
// `Stage` and `useStages` already live in features/deals/queries.ts -- the
// Kanban board's own read side against this exact endpoint, open to every role
// (`PipelineService.list` takes no `actor` and applies no role check, since every
// role needs to see the pipeline to use the board at all). `PipelinePanel`
// imports that hook directly rather than this module re-declaring a second query
// for the identical endpoint. Only the admin-only write operations the board has
// no use for live here.

type StageCreateBody = components['schemas']['PipelineStageCreate']

export function useCreateStage() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(api.POST('/api/pipeline-stages', { body: body as unknown as StageCreateBody })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.stages }),
  })
}

/**
 * `DELETE /api/pipeline-stages/{id}` is a hard delete -- unlike Customers/People/
 * Deals, `PipelineRepository.delete` calls `session.delete(stage)`, not a
 * soft-delete flag -- and it refuses with a 409 naming how many deals (archived
 * included) still point at the stage (`PipelineService.delete`'s own docstring).
 * This hook does not swallow, retry or reshape that: it only invalidates the
 * list on success, exactly like every other delete in this codebase, and leaves
 * the caller's `onError` to read `toProblem(error)` -- and its `deals` count --
 * for what the user sees. See `PipelinePanel.tsx`'s own `deleteStage` for that.
 */
export function useDeleteStage() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (stageId: string) =>
      unwrap(
        api.DELETE('/api/pipeline-stages/{stage_id}', { params: { path: { stage_id: stageId } } }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.stages }),
  })
}

export function useSeedStages() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/pipeline-stages/seed')),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.stages }),
  })
}

// -- Users ------------------------------------------------------------------

export type UserRecord = components['schemas']['UserRead']
type UserCreateBody = components['schemas']['UserCreate']
type UserUpdateBody = components['schemas']['UserUpdate']

export function useUsers() {
  return useQuery({
    queryKey: queryKeys.users,
    queryFn: () => unwrap(api.GET('/api/users')),
  })
}

export function useCreateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(api.POST('/api/users', { body: body as unknown as UserCreateBody })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.users }),
  })
}

/** Used today only to flip `attivo` (`UsersPanel`'s "Disattiva"/"Riattiva"), but
 *  takes the full partial `UserUpdate` body rather than a narrower `{attivo}`
 *  shape, since nothing about the endpoint itself is toggle-specific. */
export function useUpdateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, body }: { userId: string; body: Record<string, unknown> }) =>
      unwrap(
        api.PATCH('/api/users/{user_id}', {
          params: { path: { user_id: userId } },
          body: body as unknown as UserUpdateBody,
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.users }),
  })
}

// -- Personal access tokens ----------------------------------------------------

export type TokenRecord = components['schemas']['PatRead']
export type CreatedToken = components['schemas']['CreatedToken']

/** Scoped to the caller's own tokens server-side (`PatService.list` filters on
 *  `actor.id`), not by role -- any authenticated user, any role, can list, create
 *  and revoke their own tokens. The screen itself still lives inside the
 *  admin-only Impostazioni section for this slice (see `routes/app/impostazioni.
 *  tsx`), consistent with this task's own framing of PATs as part of "the admin
 *  side" alongside fields, pipeline and users. */
export function useTokens() {
  return useQuery({
    queryKey: queryKeys.tokens,
    queryFn: () => unwrap(api.GET('/api/tokens')),
  })
}

/**
 * The response carries the one and only copy of the plaintext token
 * (`CreatedToken.token` -- see tokens.py's own docstring: "shown once, at
 * creation, and never again"; the server stores only a SHA-256 hash). Nothing
 * here persists it beyond the caller's own state -- see `TokensPanel`'s `issued`
 * dialog for the one place it is held, and only for as long as that dialog is
 * open.
 */
export function useCreateToken() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (nome: string) => unwrap(api.POST('/api/tokens', { body: { nome } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.tokens }),
  })
}

/** Irreversible -- `PatService` has no "un-revoke", unlike a field definition's
 *  archive/unarchive pair -- so `TokensPanel` guards this behind a confirmation,
 *  the same way an irreversible pipeline-stage delete is guarded. */
export function useRevokeToken() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (tokenId: string) =>
      unwrap(api.DELETE('/api/tokens/{token_id}', { params: { path: { token_id: tokenId } } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.tokens }),
  })
}
