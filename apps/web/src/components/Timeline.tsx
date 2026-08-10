import { useQuery } from '@tanstack/react-query'
import { Bot, CircleHelp, Cog, User, type LucideIcon } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { api, toProblem, unwrap } from '@/lib/api'
import type { components } from '@/lib/api-types'
import { queryKeys } from '@/lib/query'
import type { EntityType } from '@/lib/schema'

/**
 * The wire shape of one timeline row, taken directly from the generated OpenAPI
 * schema (`components['schemas']['ActivityRead']`) rather than hand-declared: the
 * single source of truth is `ActivityRead` in
 * packages/core/src/pigrocrm/core/activities/schemas.py, and this alias tracks it
 * through `pnpm generate:api` automatically. A hand-written interface here would
 * silently drift the day that schema grows a field -- which the backend's own
 * docstring on `Activity` (activities/models.py) promises will happen ("later
 * slices append emails, documents, invoices and time entries by writing new `kind`
 * values -- no migration").
 *
 * Note `actor_type` comes through as a bare `string`, not the `'user' | 'mcp' |
 * 'system'` literal union `ActorType` is declared as in
 * packages/core/src/pigrocrm/core/actor.py: `ActivityRead.actor_type` (schemas.py)
 * widens it to `str` before it ever reaches Pydantic's own JSON Schema export, so
 * openapi-typescript has nothing narrower to generate. `actorMeta` below treats
 * every value defensively for exactly this reason -- the type system does not
 * rule out a fourth value showing up on the wire.
 */
type ActivityEntry = components['schemas']['ActivityRead']

const KIND_LABELS: Record<string, string> = {
  created: 'Creato',
  updated: 'Modificato',
  deleted: 'Archiviato',
  restored: 'Ripristinato',
  stage_changed: 'Cambio stato',
}

/**
 * Turns a snake_case value this build has no specific label for into a sentence-
 * case phrase -- e.g. a future `email_received` reads as "Email received" instead
 * of `undefined` or a blank cell. Only the first word is capitalized, matching
 * Italian convention (and this file's own `KIND_LABELS`: "Cambio stato", not
 * "Cambio Stato") rather than English-style Title Case, which would read as
 * visibly foreign next to every hand-written label around it. Not a translation
 * (the source values are already a mix of English and Italian domain words),
 * only formatting: the one honest thing to do with a value nobody taught this
 * component about yet. Shared by an unrecognised `kind`, an unrecognised
 * `actor_type`, and the generic payload fallback's field names.
 */
function humanize(value: string): string {
  const [first, ...rest] = value.split('_').filter(Boolean)
  if (!first) return '—'
  return [first.charAt(0).toUpperCase() + first.slice(1), ...rest].join(' ')
}

function labelForKind(kind: string): string {
  return KIND_LABELS[kind] ?? humanize(kind)
}

type ActorVariant = 'default' | 'secondary' | 'outline'

interface ActorMeta {
  label: string
  icon: LucideIcon
  variant: ActorVariant
}

/**
 * Keyed by the real `Actor.type` values (packages/core/src/pigrocrm/core/actor.py),
 * confirmed against a running instance of this API: a browser session records
 * "user"; a personal-access-token call -- the MCP server's own authentication,
 * pat_service.py -- records "mcp", tied to the human who owns the token, not to a
 * null actor; "system" is reserved for actor-less bootstrap actions (`Actor.
 * system()`, today only `pigrocrm createadmin`).
 *
 * The three get deliberately different *visible* treatments, not just three
 * icons at the same weight: "did I do that, or did an agent?" is the first
 * question this whole timeline exists to answer, so the answer is a coloured,
 * labelled badge -- a word, not only a glyph someone has to recognise at 12px --
 * and the one the product most wants noticed (an agent acting on someone's
 * behalf) gets the same bold fill as a primary action, not a muted secondary tag
 * indistinguishable in weight from an ordinary user edit.
 */
const ACTOR_META: Record<string, ActorMeta> = {
  user: { label: 'Utente', icon: User, variant: 'outline' },
  mcp: { label: 'Agente AI', icon: Bot, variant: 'default' },
  system: { label: 'Sistema', icon: Cog, variant: 'secondary' },
}

function actorMeta(actorType: string): ActorMeta {
  return (
    ACTOR_META[actorType] ?? { label: humanize(actorType), icon: CircleHelp, variant: 'outline' }
  )
}

function ActorBadge({ actorType }: { actorType: string }) {
  const { label, icon: Icon, variant } = actorMeta(actorType)
  return (
    <Badge variant={variant} className="shrink-0 gap-1">
      <Icon className="size-3" />
      {label}
    </Badge>
  )
}

const dateTimeFormatter = new Intl.DateTimeFormat('it-IT', { dateStyle: 'medium', timeStyle: 'short' })

/**
 * `occurred_at` is a full ISO-8601 datetime with an explicit UTC offset (verified
 * live against the real API: `"2026-08-07T20:26:33.337592Z"`), never a bare
 * "YYYY-MM-DD" -- so, unlike a date-only field (see
 * DynamicFieldRenderer.tsx's `formatIsoDateItalian` and its own docstring on
 * exactly this trap), handing it straight to `new Date(...)` is safe: there is no
 * local-midnight ambiguity to lose a day over, only a real moment in time that
 * `Intl.DateTimeFormat` then renders in the browser's own zone.
 */
function formatOccurredAt(occurredAt: string): string {
  return dateTimeFormatter.format(new Date(occurredAt))
}

/**
 * The one piece of detail worth a second line, per payload shape rather than per
 * `kind` string -- checked this way because the payload's *shape*, not the kind,
 * is what actually determines what there is to say, and a `kind` this build has
 * never seen can still carry a shape it recognises (or, worst case, falls through
 * to the generic dump below, never a crash, never `undefined`).
 *
 *  - `updated` writes `{"changed": [...]}` (customers/people/deals `service.py`).
 *  - `stage_changed` (deals only) writes `{"from": ..., "to": ...}`. Read by
 *    name, not by object key order: Postgres JSONB does not preserve insertion
 *    order (confirmed live -- the real API returned `{"to": ..., "from": ...}`
 *    for a payload the backend constructs as `{"from": ..., "to": ...}`), so
 *    anything that assumed the first key was always "from" would be reading the
 *    wrong side of the transition at random.
 *  - `created`'s payload is per-entity (`ragione_sociale` for a customer, `nome`
 *    for a person, `nome`+`stage` for a deal) and `deleted`/`restored` carry `{}`
 *    -- both land in the generic fallback, which is `null` for the empty case
 *    (the label above already says everything there is to say) and an
 *    ugly-but-true `snake_case: value` dump otherwise, which beats saying
 *    nothing about a real event.
 */
function ActivityDetail({ payload }: { payload: ActivityEntry['payload'] }) {
  if (Array.isArray(payload.changed) && payload.changed.length > 0) {
    return (
      <p className="mt-1 text-sm text-muted-foreground">
        Campi modificati: {payload.changed.map((field) => humanize(String(field))).join(', ')}
      </p>
    )
  }

  if ('from' in payload && 'to' in payload) {
    return (
      <p className="mt-1 text-sm text-muted-foreground">
        Da <strong className="font-medium text-foreground">{String(payload.from)}</strong> a{' '}
        <strong className="font-medium text-foreground">{String(payload.to)}</strong>
      </p>
    )
  }

  const rest = Object.entries(payload)
  if (rest.length === 0) return null
  return (
    <p className="mt-1 text-sm text-muted-foreground">
      {rest.map(([key, value]) => `${humanize(key)}: ${String(value)}`).join(' · ')}
    </p>
  )
}

// Three explicit branches, not a shared helper keyed off a path template: the
// path parameter *name* differs per entity (customer_id/person_id/deal_id), and
// that name is exactly what a generated client type-checks against the live
// OpenAPI document. This is the "small discriminated union" alternative to the
// original plan's `api.GET(PATHS[entityType] as never, { params: { ... } as
// never })` -- every branch below is still checked against `paths` in
// lib/api-types.ts, so a renamed path or parameter fails `tsc`, not silently at
// runtime the way the two `as never` casts would have.
const TIMELINE_FETCHERS: Record<
  EntityType,
  (entityId: string, limit: number) => Promise<ActivityEntry[]>
> = {
  customer: (entityId, limit) =>
    unwrap(
      api.GET('/api/customers/{customer_id}/timeline', {
        params: { path: { customer_id: entityId }, query: { limit } },
      }),
    ),
  person: (entityId, limit) =>
    unwrap(
      api.GET('/api/people/{person_id}/timeline', {
        params: { path: { person_id: entityId }, query: { limit } },
      }),
    ),
  deal: (entityId, limit) =>
    unwrap(
      api.GET('/api/deals/{deal_id}/timeline', {
        params: { path: { deal_id: entityId }, query: { limit } },
      }),
    ),
}

interface TimelineProps {
  entityType: EntityType
  entityId: string
  /**
   * The backend's own bound (routers/{customers,people,deals}.py's shared
   * `Query(ge=1, le=200)`, mirrored again in `ActivityService.timeline` itself so
   * the MCP `get_timeline` tool -- which calls that method directly, with no REST
   * schema in between -- cannot bypass it either): asking for more than 200 or
   * fewer than 1 gets a 422, not a silently clamped value. This default only
   * matches the backend's own default of 50 when the prop is omitted; it does not
   * re-enforce the bound client-side, so a caller that passes an out-of-range
   * value sees the same validation error curl would get, through the usual
   * `toProblem` path, rather than having it masked here.
   */
  limit?: number
}

/**
 * One entry per row: which actor did it (a badge, always visible, never a subtle
 * icon-only difference), what happened (`kind`, humanized if this build does not
 * recognise it yet), when (localized Italian date and time), and whatever extra
 * the payload has to say.
 */
export function Timeline({ entityType, entityId, limit = 50 }: TimelineProps) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: [...queryKeys.timeline(entityType, entityId), limit],
    queryFn: () => TIMELINE_FETCHERS[entityType](entityId, limit),
  })

  if (isLoading) {
    return (
      <div className="space-y-3" role="status" aria-label="Caricamento timeline">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} className="h-16 w-full" />
        ))}
      </div>
    )
  }

  // A failed request is not the same claim as "nothing happened yet" -- showing
  // the empty state here would be a confident lie about a request that never
  // actually completed. `toProblem` accepts the raw `unknown` react-query hands
  // back (see its own docstring: the query fn above only ever rejects with an
  // already-normalised `ProblemDetail`, via `unwrap`) and gives back the same
  // honest Italian message every other failure path in this app shows.
  if (isError) {
    return <p className="text-sm text-destructive">{toProblem(error).detail}</p>
  }

  if (!data || data.length === 0) {
    return <p className="text-muted-foreground">Nessuna attività registrata.</p>
  }

  return (
    <ol className="space-y-3">
      {data.map((entry) => (
        <li key={entry.id} className="flex items-start gap-3 rounded-md border p-3">
          <ActorBadge actorType={entry.actor_type} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <span className="font-medium">{labelForKind(entry.kind)}</span>
              <time dateTime={entry.occurred_at} className="shrink-0 text-xs text-muted-foreground">
                {formatOccurredAt(entry.occurred_at)}
              </time>
            </div>
            <ActivityDetail payload={entry.payload} />
          </div>
        </li>
      ))}
    </ol>
  )
}
