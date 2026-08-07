import createClient from 'openapi-fetch'
import type { paths } from './api-types'

export const api = createClient<paths>({
  // Empty, not '/api': every router (apps/api/src/pigrocrm_api/routers/*.py) already
  // declares its own "/api/..." prefix, so `paths` below -- generated straight from
  // the live OpenAPI document -- has full keys like "/api/auth/me", never bare
  // "/auth/me". Vite's dev proxy (vite.config.ts) matches the same "/api" prefix and
  // forwards it unmodified, so the exact same full path also reaches the right
  // route in production, behind whatever serves this build there.
  baseUrl: '',
  // The JWT lives in an httpOnly cookie: JavaScript never sees it, and every
  // request carries it automatically.
  credentials: 'include',
})

export interface ProblemDetail {
  type: string
  title: string
  status: number
  detail: string
  code: string
  entity?: string
  field?: string
  reason?: string
  expected?: string
  [key: string]: unknown
}

const GENERIC: ProblemDetail = {
  type: 'about:blank',
  title: 'Errore',
  status: 0,
  detail: 'Si è verificato un errore imprevisto. Riprova.',
  code: 'unknown',
}

interface FastApiValidationError {
  loc: (string | number)[]
  msg: string
  type: string
}

/** FastAPI's own request-validation shape: `{ detail: [{ type, loc, msg }, ...] }`.
 *  Structural, not a Content-Type sniff -- openapi-fetch parses every non-2xx body
 *  with a blind `JSON.parse` regardless of header (see its source), so the only way
 *  to tell this apart from the domain problem document below is the shape of
 *  `detail` itself: an array here, a string there.
 *
 *  Return type is a non-empty tuple, not a plain array: under `noUncheckedIndexedAccess`
 *  (tsconfig.json), destructuring element 0 of `T[]` still types as `T | undefined` --
 *  the tuple form is what lets the caller destructure `[first]` and get `T` back,
 *  since a non-empty check was already made right here, once. */
function asFastApiValidationErrors(
  value: object,
): [FastApiValidationError, ...FastApiValidationError[]] | null {
  const detail = (value as { detail?: unknown }).detail
  if (!Array.isArray(detail) || detail.length === 0) return null
  const [first] = detail as unknown[]
  if (
    typeof first !== 'object' ||
    first === null ||
    !Array.isArray((first as { loc?: unknown }).loc) ||
    typeof (first as { msg?: unknown }).msg !== 'string'
  ) {
    return null
  }
  return detail as [FastApiValidationError, ...FastApiValidationError[]]
}

/**
 * Normalises every shape an API call can fail with into one `ProblemDetail`, so
 * every consumer -- a toast, a form field, the query retry policy -- reads the same
 * three or four properties no matter which of these produced it:
 *
 *  - the domain problem document (RFC 9457, `application/problem+json`): a
 *    `DomainError` rendered by `domain_error_handler` -- `code`/`detail`/`field`/...
 *    already at the top level, passed through unchanged.
 *  - FastAPI's own request-validation error (`application/json`): the request never
 *    reached an endpoint at all (a non-UUID path segment, a malformed body), so
 *    there is no domain `code` -- `detail` is an array of `{ type, loc, msg }`
 *    instead of a string. Both shapes are declared for the same 422 in the OpenAPI
 *    document on purpose (see `_domain_and_request_validation_response` in
 *    `apps/api/src/pigrocrm_api/errors.py`) precisely so this function has
 *    something real to normalise. The field pydantic actually complained about is
 *    always the *last* segment of `loc` -- everything before it is the path to get
 *    there, e.g. `["body", "customer", "partita_iva"]`.
 *  - a bare `HTTPException` (`application/json`, `{ detail: "<message>" }`, no
 *    `code`): every one of these in this API is a 401 -- login's own credentials
 *    check, and get_actor's/refresh's "the session is gone" checks (see
 *    `pigrocrm_api/deps.py` and `pigrocrm_api/routers/auth.py`). Worth keeping the
 *    real message over the generic fallback below even without a `code` to key off.
 *  - anything else -- a thrown network `Error`, `null`, garbage -- becomes the
 *    generic Italian fallback. `detail` is never undefined from this function.
 */
export function toProblem(error: unknown): ProblemDetail {
  if (!error || typeof error !== 'object') return GENERIC

  const validationErrors = asFastApiValidationErrors(error)
  if (validationErrors) {
    const [first] = validationErrors
    const field = first.loc.length > 0 ? String(first.loc[first.loc.length - 1]) : undefined
    return {
      ...GENERIC,
      title: 'Dati non validi',
      status: 422,
      detail: first.msg,
      code: 'validation_failed',
      field,
      reason: first.msg,
    }
  }

  const err = error as { code?: unknown; detail?: unknown }
  if (typeof err.code === 'string' && typeof err.detail === 'string') {
    return error as ProblemDetail
  }
  if (typeof err.detail === 'string') {
    return { ...GENERIC, detail: err.detail, code: 'unauthenticated' }
  }

  return GENERIC
}

/** The API already decided what is wrong and why. The UI only points at it. */
export function fieldErrorFrom(problem: ProblemDetail): { field: string; message: string } | null {
  if (problem.code !== 'validation_failed' || !problem.field) return null
  const reason = problem.reason ?? problem.detail
  const message = problem.expected ? `${reason} (atteso: ${problem.expected})` : reason
  return { field: problem.field, message }
}

/**
 * Throws the problem document itself, so every consumer gets structured data --
 * never a raw `Response` or an untyped `unknown`.
 *
 * openapi-fetch's parsed `error` body never carries the real HTTP status (it comes
 * from a blind `JSON.parse` of the response text -- see its source): the domain
 * problem document happens to embed one anyway (RFC 9457's own `status` field), but
 * a bare `HTTPException` body (`{ detail: "<message>" }`, e.g. every 401 in this
 * API) does not. `response.status` is the one place that number is never ambiguous,
 * so it always wins here. This is what makes `queryClient`'s retry policy able to
 * ask "was this a 401?" at all -- silently losing it would make that check never
 * fire for the exact case it exists for.
 */
export async function unwrap<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await promise.catch((networkError: unknown) => {
    // fetch() itself throws for a true network failure (offline, DNS, CORS) --
    // openapi-fetch never gets a chance to run, so there is no `response` at all
    // here, unlike every other branch below.
    throw toProblem(networkError)
  })
  if (error !== undefined) throw { ...toProblem(error), status: response.status }
  return data as T
}
