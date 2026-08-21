import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { api, unwrap } from '@/lib/api'
import type { components } from '@/lib/api-types'
import type { EntityType } from '@/lib/schema'
import { queryKeys } from '@/lib/query'

// -- Field definitions --------------------------------------------------------

export type FieldDefinitionRecord = components['schemas']['FieldDefinitionRead']
type FieldDefinitionCreateBody = components['schemas']['FieldDefinitionCreate']
type FieldDefinitionUpdateBody = components['schemas']['FieldDefinitionUpdate']

/**
 * `include_archived: true`, always -- unlike `useEntitySchema` (lib/schema.ts),
 * which only needs what Customers/Persons/Deals currently render and excludes
 * archived fields by design, this admin screen's job is to also show what has
 * been archived, with a way back (`FieldsPanel`'s "Ripristina").
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

/** Invalidates both this admin list and `queryKeys.schema` -- the second is
 *  what makes a field created/archived/restored/edited here show up (or
 *  disappear) on Customers/Persons/Deals immediately. Keyed off the response's
 *  own `entity_type`, never a caller-supplied one. */
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

/** `FieldDefinitionUpdate` accepts `label`/`options`/`required`/`position` --
 *  `key`/`field_type`/`entity_type` are absent from the schema itself (identity,
 *  not a label; see that schema's own docstring), so there is nothing to guard
 *  client-side: the backend already has no spelling that would change them. */
export function useUpdateFieldDefinition() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ fieldId, body }: { fieldId: string; body: Record<string, unknown> }) =>
      unwrap(
        api.PATCH('/api/field-definitions/{field_id}', {
          params: { path: { field_id: fieldId } },
          body: body as unknown as FieldDefinitionUpdateBody,
        }),
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

/** Symmetric to `useArchiveFieldDefinition` -- without this, archiving would be
 *  a one-way door in the UI even though the data model treats it as
 *  reversible. See `FieldsPanel.tsx`'s "Ripristina". */
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
// `Stage`/`useStages` already live in features/deals/queries.ts (the Kanban
// board's own read side, open to every role -- `PipelineService.list` applies
// no role check). `PipelinePanel` imports that hook directly; only the
// admin-only writes the board has no use for live here.

type StageCreateBody = components['schemas']['PipelineStageCreate']

export function useCreateStage() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(api.POST('/api/pipeline-stages', { body: body as unknown as StageCreateBody })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.stages }),
  })
}

/** `DELETE /api/pipeline-stages/{id}` is a hard delete (`PipelineRepository.
 *  delete` calls `session.delete`, not a soft-delete flag) that refuses with a
 *  409 naming how many deals -- archived included -- still point at the stage.
 *  This hook does not reshape that; `PipelinePanel.remove` reads `toProblem`
 *  and its `deals` count for what the user sees. */
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

/**
 * Used for both the active/inactive toggle and the role select in
 * `UsersPanel`. Writes the server's own response straight into the cached
 * list (`setQueryData`) instead of invalidating and trusting a second round
 * trip to succeed.
 *
 * That second round trip is exactly what used to lie: deactivating your own
 * account kills your session as a side effect of the PATCH succeeding, so the
 * background refetch this hook used to trigger came back 401 -- and
 * `DataTable` deliberately keeps showing the last good page on a background
 * error (see its own docstring), which left "Attivo" on screen next to a
 * toast that had already said "Utente disattivato". The PATCH response is the
 * authoritative answer to "did this work", already in hand the moment
 * `onSuccess` runs; a second request that can independently fail for
 * unrelated reasons was never necessary to trust it.
 */
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
    onSuccess: (updated) => {
      queryClient.setQueryData<UserRecord[]>(queryKeys.users, (previous) =>
        previous?.map((user) => (user.id === updated.id ? updated : user)),
      )
    },
  })
}

// -- Templates (admin writes) -------------------------------------------------

// `Template`/`useTemplates` already live in features/documents/queries.ts: the
// new-from-template dialog reads them and is open to every role, since
// `TemplateService.list` applies no role check. Only the admin-only writes,
// which that dialog has no use for, live here.

type TemplateCreateBody = components['schemas']['TemplateCreate']
type TemplateUpdateBody = components['schemas']['TemplateUpdate']

function invalidateTemplates(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.templates() })
}

export function useCreateTemplate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(api.POST('/api/templates', { body: body as unknown as TemplateCreateBody })),
    onSuccess: () => invalidateTemplates(queryClient),
  })
}

export function useUpdateTemplate(templateId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(
        api.PATCH('/api/templates/{template_id}', {
          params: { path: { template_id: templateId } },
          body: body as unknown as TemplateUpdateBody,
        }),
      ),
    onSuccess: () => invalidateTemplates(queryClient),
  })
}

/** `DELETE /api/templates/{id}` deactivates rather than deleting: it flips
 *  `attivo` and returns the row. Paired with `useActivateTemplate` deliberately
 *  -- an administrator who deactivates a template by mistake must have a way
 *  back, the same lesson `useUnarchiveFieldDefinition` exists for. A one-way
 *  door on a boolean column is a defect, not a simplification. */
export function useDeactivateTemplate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (templateId: string) =>
      unwrap(
        api.DELETE('/api/templates/{template_id}', {
          params: { path: { template_id: templateId } },
        }),
      ),
    onSuccess: () => invalidateTemplates(queryClient),
  })
}

export function useActivateTemplate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (templateId: string) =>
      unwrap(
        api.POST('/api/templates/{template_id}/activate', {
          params: { path: { template_id: templateId } },
        }),
      ),
    onSuccess: () => invalidateTemplates(queryClient),
  })
}

// -- Emitter profile ----------------------------------------------------------

export type EmitterRecord = components['schemas']['EmitterProfileRead']
type EmitterUpsertBody = components['schemas']['EmitterProfileUpsert']

/**
 * One row, or none at all on a fresh install. `GET /api/emitter` answers 404
 * until it is first saved, and that 404 is not an error the user needs to see --
 * it means "not configured yet", which is this panel's empty state. Every other
 * failure still surfaces, which is why this keys on the status rather than
 * swallowing everything.
 */
export function useEmitter() {
  return useQuery({
    queryKey: queryKeys.emitter,
    queryFn: async () => {
      const { data, error, response } = await api.GET('/api/emitter')
      if (response.status === 404) return null
      if (error) throw error
      return data ?? null
    },
  })
}

/** `PUT`, not `PATCH`: `EmitterProfileUpsert` is one shape for create and
 *  update, because there is only ever one row and both need the same fields.
 *  Slice 3 builds FatturaPA on this row, so a partial save leaving
 *  `partita_iva` empty would surface much later as an invalid invoice. */
export function useSaveEmitter() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      unwrap(api.PUT('/api/emitter', { body: body as unknown as EmitterUpsertBody })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.emitter }),
  })
}
