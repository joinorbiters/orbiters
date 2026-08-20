import { useQuery } from '@tanstack/react-query'
import { api, unwrap } from './api'
import { queryKeys } from './query'

/** The nine field types the dynamic-field system supports (mirrors `FieldType` in
 *  packages/core/src/pigrocrm/core/fields/types.py — the one place that would need
 *  a tenth entry added, never here first). */
export type FieldType =
  | 'text'
  | 'textarea'
  | 'number'
  | 'currency'
  | 'date'
  | 'select'
  | 'multiselect'
  | 'checkbox'
  | 'url'

/**
 * One custom field, exactly as `GET /api/schema/{entity_type}` puts it on the wire.
 *
 * Verified live rather than assumed: brought up the API against a throwaway
 * Postgres, created one field of every type on `customer`, and read the real
 * response. It matches `describe_specs` in
 * packages/core/src/pigrocrm/core/fields/dynamic.py field for field — `type`, not
 * `field_type` (that rename happens on purpose, in that one function), `options`
 * always an array (`[]` when the type has none), `required` a plain boolean:
 *
 *   { "key": "segmento", "label": "Segmento", "type": "select", "required": false,
 *     "options": ["Enterprise", "PMI", "Startup"] }
 *
 * `describe_specs` is also exactly what the MCP `describe_schema` tool calls, so
 * this type describes both adapters' idea of a field at once, not just this one.
 */
export interface FieldDefinition {
  key: string
  label: string
  type: FieldType
  required: boolean
  options: string[]
}

export type EntityType = 'customer' | 'person' | 'deal' | 'document'

export interface EntitySchema {
  entity_type: string
  native_fields: string[]
  custom_fields: FieldDefinition[]
}

/**
 * Reads the live shape of an entity — the same document the MCP `describe_schema`
 * tool returns, so the UI and an agent can never disagree about what fields exist.
 *
 * The path is `/api/schema/{entity_type}`, not the bare `/schema/{entity_type}`:
 * every router in apps/api/src/pigrocrm_api/routers/*.py declares its own "/api"
 * prefix, and lib/api.ts's client is built with `baseUrl: ''` to match — confirmed
 * live, the bare path 404s.
 *
 * The cast below is not a shortcut: `apps/api/src/pigrocrm_api/routers/schema.py`
 * declares `EntitySchema.custom_fields` as `list[dict[str, Any]]`, so that's as far
 * as FastAPI's own OpenAPI document — and therefore openapi-typescript's generated
 * `components["schemas"]["EntitySchema"]` — can describe it: `{ [key: string]:
 * unknown }[]`, not the real per-field shape. `FieldDefinition` above is that real
 * shape, established by reading `describe_specs` and confirmed against the live
 * response, so this is where the gap between the generated type and reality gets
 * closed, once, for every caller of this hook.
 */
export function useEntitySchema(entityType: EntityType) {
  return useQuery({
    queryKey: queryKeys.schema(entityType),
    queryFn: async (): Promise<EntitySchema> => {
      const schema = await unwrap(
        api.GET('/api/schema/{entity_type}', { params: { path: { entity_type: entityType } } }),
      )
      return schema as unknown as EntitySchema
    },
  })
}
