/**
 * What the CRM tells PostHog beyond pageviews and clicks, and where it says it.
 *
 * The activation funnel is read off the API client rather than written into the
 * features. `lib/api.ts` is the one `openapi-fetch` client, and every write the funnel
 * cares about goes through it, so one middleware on that client turns a closed table of
 * successful calls into named events. A feature file never mentions analytics, and an
 * action counts only when the API said yes: a 422 on «Nuovo cliente» is not a customer.
 *
 * Identity follows the session the same way: `AuthProvider` calls `identifySession`
 * when `me` answers a person, and `forgetSession` when they leave or the session is gone.
 * Design: docs/design/2026-09-12-posthog-analytics-design.md, «The CRM (ORB-184)».
 */
import { capture, identifyGroup, identifyUser, resetUser } from '@orbiters/analytics/browser'
import type { Middleware } from 'openapi-fetch'
import type { SessionUser } from './auth'
import { tenantPrefix } from './tenant'

/**
 * `METHOD /path` as the OpenAPI document spells it, with the space's prefix and any
 * trailing slash removed first. Closed on purpose: nothing else the client does is an
 * event, and «first customer» or «activated within seven days» are funnels PostHog
 * computes from these, not something the code decides.
 */
const EVENTS: ReadonlyMap<string, string> = new Map([
  ['POST /api/tenants', 'spazio_creato'],
  ['POST /api/auth/entra', 'entrato_con_link'],
  ['POST /api/customers', 'cliente_creato'],
  ['POST /api/deals', 'deal_creato'],
  ['POST /api/documents', 'documento_creato'],
  ['POST /api/time-entries', 'ore_registrate'],
  ['POST /api/invoices', 'fattura_emessa'],
  ['POST /api/tokens', 'assistente_collegato'],
  ['PUT /api/emitter', 'profilo_emittente_salvato'],
])

/**
 * The pathname the table is keyed on. Under a space every request is `/<slug>/api/...`
 * (the client's `baseUrl`, lib/api.ts), so the prefix goes first; the trailing slash
 * goes because `/api/tenants/` is served with one and its siblings are not, and the
 * table should not have to remember which is which.
 */
function tablePath(pathname: string, prefix: string): string {
  const own = prefix !== '' && (pathname === prefix || pathname.startsWith(`${prefix}/`))
  const bare = own ? pathname.slice(prefix.length) : pathname
  return bare.length > 1 ? bare.replace(/\/+$/, '') : bare
}

/** The event a successful call earns, or undefined for everything the table leaves out. */
export function eventFor(method: string, pathname: string, prefix: string): string | undefined {
  return EVENTS.get(`${method.toUpperCase()} ${tablePath(pathname, prefix)}`)
}

/**
 * The middleware itself, registered from `main.tsx` rather than inside `lib/api.ts` so
 * the client stays a plain typed fetch in every test that stubs it. `onResponse` sees
 * the response after `sendRefreshingSession` has already retried an expired session,
 * so a call that succeeded on the second try counts once, and a call that stayed 401
 * does not count at all.
 */
export function analyticsMiddleware(prefix: string = tenantPrefix): Middleware {
  return {
    onResponse({ request, response }) {
      if (!response.ok) return
      const event = eventFor(request.method, new URL(request.url).pathname, prefix)
      if (event !== undefined) capture(event)
    },
  }
}

/** The group key for a space: its slug, or `root` for the installation with no prefix. */
export function spaceKey(prefix: string): string {
  return prefix === '' ? 'root' : prefix.slice(1)
}

/** The person and the space they are in. Email and name are sent on purpose: Ivan
 *  chose to see who a session belongs to (design, «What was decided»). */
export function identifySession(
  user: Pick<SessionUser, 'id' | 'email' | 'nome' | 'ruolo'>,
  prefix: string = tenantPrefix,
): void {
  identifyUser(user.id, { email: user.email, nome: user.nome, ruolo: user.ruolo })
  identifyGroup('spazio', spaceKey(prefix))
}

/** Forgets the person: on logout, and when the session vanished without one. */
export function forgetSession(): void {
  resetUser()
}
