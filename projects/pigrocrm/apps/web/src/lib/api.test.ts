import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, fetchWithRefresh, fieldErrorFrom, toProblem, unwrap } from './api'

// The domain problem document: an RFC 9457 body `domain_error_handler` renders for
// any DomainError (apps/api/src/pigrocrm_api/errors.py) -- application/problem+json,
// `detail` a string, `code`/`field`/`reason`/`expected` alongside it.
const PROBLEM = {
  type: 'https://pigrocrm.dev/errors/validation_failed',
  title: 'Dati non validi',
  status: 422,
  detail: 'customer.partita_iva: deve essere di 11 cifre',
  code: 'validation_failed',
  entity: 'customer',
  field: 'partita_iva',
  reason: 'deve essere di 11 cifre',
  expected: '11 cifre numeriche',
}

// FastAPI's own request-validation error: the request never reached an endpoint at
// all (here, a non-UUID path segment), so there is no domain `code` -- `detail` is
// an array of `{ type, loc, msg }` instead of a string. Declared alongside the
// domain shape for every 422 in the OpenAPI document on purpose (see
// _domain_and_request_validation_response in pigrocrm_api/errors.py); shape below
// pinned to the real `ValidationError` schema openapi-typescript generated from it
// (loc: (string | number)[], msg: string, type: string, plus optional input/ctx).
const FASTAPI_VALIDATION_ERROR = {
  detail: [
    {
      type: 'uuid_parsing',
      loc: ['path', 'customer_id'],
      msg: 'Input non valido: non è uno UUID',
      input: 'non-un-uuid',
    },
  ],
}

// A bare HTTPException, the shape every 401 in this API actually returns (login's
// wrong-credentials check, get_actor's and refresh's "the session is gone" checks --
// see pigrocrm_api/deps.py and pigrocrm_api/routers/auth.py): no `code` at all.
const BARE_UNAUTHENTICATED = { detail: 'Autenticazione richiesta' }

describe('toProblem', () => {
  it('passes a domain problem document through unchanged', () => {
    expect(toProblem(PROBLEM)).toEqual(PROBLEM)
    expect(toProblem(PROBLEM).code).toBe('validation_failed')
  })

  it('normalises a FastAPI request-validation array into the same shape', () => {
    const problem = toProblem(FASTAPI_VALIDATION_ERROR)
    expect(problem.code).toBe('validation_failed')
    expect(problem.status).toBe(422)
    expect(problem.field).toBe('customer_id')
    expect(problem.detail).toBe('Input non valido: non è uno UUID')
  })

  it('keeps the real message from a bare HTTPException even without a code', () => {
    const problem = toProblem(BARE_UNAUTHENTICATED)
    expect(problem.detail).toBe('Autenticazione richiesta')
  })

  it('turns an unknown failure into a readable Italian message', () => {
    const problem = toProblem(new Error('network down'))
    expect(problem.code).toBe('unknown')
    expect(problem.detail).toMatch(/errore/i)
  })

  it('turns a garbage object with no recognisable shape into the same fallback', () => {
    const problem = toProblem({ whatever: 'this is not a problem document' })
    expect(problem.code).toBe('unknown')
    expect(problem.detail).toMatch(/errore/i)
  })

  it('never returns undefined for detail', () => {
    expect(toProblem(null).detail).toBeTruthy()
    expect(toProblem(undefined).detail).toBeTruthy()
  })
})

// Fix round 1: main.py registers an exception handler only for DomainError, so
// FastAPI's own default HTTPException handler is what renders everything else --
// including a 404 for a route nothing matches, and a 405 for a wrong method on a
// route that exists. Both render through the exact same bare `{ detail: "<message>" }`
// shape as every deliberate 401 in this API, with no `code` either way. Reproduced
// live against the real backend: GET /auth/me (missing the /api prefix) -> 404
// {"detail":"Not Found"}; DELETE /api/auth/me -> 405 {"detail":"Method Not Allowed"}.
// Shape alone cannot tell these apart from a real 401 -- only the transport-level
// status can, and toProblem doesn't see it unless told: hence the second parameter.
describe('toProblem — authentication is decided by status, never by body shape alone', () => {
  it('does not call a 404 with this shape "unauthenticated"', () => {
    expect(toProblem({ detail: 'Not Found' }, 404).code).not.toBe('unauthenticated')
  })

  it('does not call a 405 with this shape "unauthenticated"', () => {
    expect(toProblem({ detail: 'Method Not Allowed' }, 405).code).not.toBe('unauthenticated')
  })

  it('calls a real 401 with this shape "unauthenticated"', () => {
    expect(toProblem(BARE_UNAUTHENTICATED, 401).code).toBe('unauthenticated')
  })

  it('gives a 404 an honest generic code instead, without losing its status or message', () => {
    const problem = toProblem({ detail: 'Not Found' }, 404)
    expect(problem.code).toBe('http_error')
    expect(problem.status).toBe(404)
    expect(problem.detail).toBe('Not Found')
  })

  it('does not guess "unauthenticated" when no status is given at all', () => {
    // toProblem(error) alone -- the shape every direct, status-free call site uses
    // (including every other test in this file) -- must not assume 401 just because
    // the body happens to look like one of this API's real 401s.
    expect(toProblem(BARE_UNAUTHENTICATED).code).not.toBe('unauthenticated')
  })
})

describe('fieldErrorFrom', () => {
  it('extracts the offending field from a domain problem document', () => {
    expect(fieldErrorFrom(toProblem(PROBLEM))).toEqual({
      field: 'partita_iva',
      message: 'deve essere di 11 cifre (atteso: 11 cifre numeriche)',
    })
  })

  it('extracts the offending field from a FastAPI validation array, from the last element of loc', () => {
    expect(fieldErrorFrom(toProblem(FASTAPI_VALIDATION_ERROR))).toEqual({
      field: 'customer_id',
      message: 'Input non valido: non è uno UUID',
    })
  })

  it('returns null when the problem is not about a field', () => {
    expect(fieldErrorFrom(toProblem({ ...PROBLEM, code: 'conflict', field: undefined }))).toBeNull()
  })

  it('returns null for the generic fallback, which is never about one specific field', () => {
    expect(fieldErrorFrom(toProblem(new Error('network down')))).toBeNull()
  })
})

describe('unwrap', () => {
  it('resolves with the data on success', async () => {
    const response = new Response(null, { status: 200 })
    await expect(
      unwrap(Promise.resolve({ data: { id: '1' }, response })),
    ).resolves.toEqual({ id: '1' })
  })

  it('attaches the real HTTP status even to a body that does not embed one, and correctly calls it unauthenticated', async () => {
    // The exact shape login/me/refresh return for a 401: openapi-fetch's parsed
    // `error` never carries the response's own status code (see api.ts's docstring
    // on unwrap), so without this, queryClient's retry policy could never see 401
    // for the one family of responses that matters most for it.
    const response = new Response(null, { status: 401 })
    await expect(
      unwrap(Promise.resolve({ error: BARE_UNAUTHENTICATED, response })),
    ).rejects.toMatchObject({ status: 401, code: 'unauthenticated', detail: 'Autenticazione richiesta' })
  })

  // Fix round 1: reproduces, through the actual unwrap() call path, the two live
  // responses the reviewer found -- a 404 for a mistyped path and a 405 for a wrong
  // method, both rendered by FastAPI's own default handler through the identical
  // bare-detail shape every 401 uses. Neither may come out "unauthenticated": only
  // unwrap has the real response.status, so this is where the distinction must hold.
  it('does not call a 404 "unauthenticated" -- GET /auth/me (no /api prefix) reproduced live', async () => {
    const response = new Response(null, { status: 404 })
    await expect(
      unwrap(Promise.resolve({ error: { detail: 'Not Found' }, response })),
    ).rejects.toMatchObject({ status: 404, code: 'http_error' })
  })

  it('does not call a 405 "unauthenticated" -- DELETE /api/auth/me reproduced live', async () => {
    const response = new Response(null, { status: 405 })
    await expect(
      unwrap(Promise.resolve({ error: { detail: 'Method Not Allowed' }, response })),
    ).rejects.toMatchObject({ status: 405, code: 'http_error' })
  })

  it('normalises a network-level failure into a ProblemDetail too, not a raw error', async () => {
    await expect(unwrap(Promise.reject(new TypeError('Failed to fetch')))).rejects.toMatchObject({
      code: 'unknown',
    })
  })
})

/**
 * `fetchWithRefresh` exists because two callers cannot use `openapi-fetch` at all:
 * `downloadInvoiceArtifact` and `downloadDocument` want a `Blob` and the server's own
 * `Content-Disposition`, which the typed client has no way to express. They were raw
 * `fetch(..., {credentials:'include'})` calls, and the fifteen-minute access cookie
 * meant the PDF button answered «Autenticazione richiesta» after any quiet spell.
 */
describe('fetchWithRefresh', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function unauthenticated() {
    return new Response(JSON.stringify({ detail: 'Autenticazione richiesta' }), { status: 401 })
  }

  it('sends the session cookie and passes a 2xx straight through', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response('ok', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const response = await fetchWithRefresh('/api/x')

    expect(response.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ credentials: 'include' })
  })

  it('refreshes once and retries the original request on a 401', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(unauthenticated())
      .mockResolvedValueOnce(new Response(null, { status: 200 }))
      .mockResolvedValueOnce(new Response('ok', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const response = await fetchWithRefresh('/api/x')

    expect(response.status).toBe(200)
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/x',
      '/api/auth/refresh',
      '/api/x',
    ])
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({ method: 'POST', credentials: 'include' })
  })

  it('returns the original 401 when the refresh fails, so the caller says "session gone"', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(unauthenticated())
      .mockResolvedValueOnce(unauthenticated())
    vi.stubGlobal('fetch', fetchMock)

    const response = await fetchWithRefresh('/api/x')

    expect(response.status).toBe(401)
    // The original response's body is untouched and still readable: the caller parses
    // it into a problem document.
    expect(await response.json()).toEqual({ detail: 'Autenticazione richiesta' })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('refreshes once for two requests that expire together', async () => {
    // A rotating refresh token is single-use, and `RefreshTokenService.consume`
    // treats a replay as a compromise and revokes *every* token the user holds
    // (apps/api/src/pigrocrm_api/routers/auth.py). Two downloads that both meet a
    // 401 must therefore share one refresh, or the pair logs the owner out.
    let refreshes = 0
    const fetchMock = vi.fn<typeof fetch>().mockImplementation((input) => {
      const url = String(input)
      if (url.endsWith('/api/auth/refresh')) {
        refreshes += 1
        return Promise.resolve(new Response(null, { status: 200 }))
      }
      return Promise.resolve(
        refreshes === 0 ? unauthenticated() : new Response('ok', { status: 200 }),
      )
    })
    vi.stubGlobal('fetch', fetchMock)

    const [a, b] = await Promise.all([fetchWithRefresh('/api/a'), fetchWithRefresh('/api/b')])

    expect([a.status, b.status]).toEqual([200, 200])
    expect(refreshes).toBe(1)
  })
})

/**
 * The same second chance, for every request that goes through the typed client --
 * which is all of them but the two downloads above.
 *
 * The bug this pins: the access cookie lasts fifteen minutes
 * (`access_token_minutes`), the refresh cookie a hundred and eighty days, and a
 * `POST /api/auth/refresh` renews the pair. Nothing in the client asked for that
 * renewal, so after a quiet quarter of an hour *every* screen answered
 * «Autenticazione richiesta» -- with a good refresh cookie in the jar -- until the
 * owner reloaded the page. Reported from production.
 *
 * `baseUrl` is passed per call throughout: in a browser `new Request('/api/auth/me')`
 * resolves against the document, but the `Request` this test environment provides is
 * Node's, which rejects a relative URL outright. The production client keeps its own
 * empty/`/<slug>` base (see `api` in lib/api.ts) -- only these tests need to spell an
 * origin.
 */
describe('the typed client', () => {
  const BASE = 'http://localhost:3000'

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function unauthenticated() {
    return new Response(JSON.stringify({ detail: 'Autenticazione richiesta' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  function json(payload: unknown) {
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  /** Whatever each attempt actually addressed, Request or plain string alike. */
  function urls(mock: ReturnType<typeof vi.fn<typeof fetch>>): string[] {
    return mock.mock.calls.map(([input]) =>
      input instanceof Request ? input.url : String(input),
    )
  }

  const ME = {
    id: '11111111-1111-1111-1111-111111111111',
    email: 'titolare@studio.it',
    nome: 'Titolare',
    ruolo: 'admin',
    attivo: true,
  }

  it('refreshes once on a 401 and returns the data the retry produced', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(unauthenticated())
      .mockResolvedValueOnce(new Response(null, { status: 200 }))
      .mockResolvedValueOnce(json(ME))
    vi.stubGlobal('fetch', fetchMock)

    const user = await unwrap(api.GET('/api/auth/me', { baseUrl: BASE }))

    expect(user).toMatchObject({ email: 'titolare@studio.it' })
    expect(urls(fetchMock)).toEqual([
      `${BASE}/api/auth/me`,
      '/api/auth/refresh',
      `${BASE}/api/auth/me`,
    ])
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({ method: 'POST', credentials: 'include' })
  })

  it('refreshes exactly once for two calls whose cookie expired together', async () => {
    // A rotating refresh token is single-use, and `RefreshTokenService.consume`
    // treats a replay as a compromised credential and revokes every token the user
    // holds (apps/api/src/pigrocrm_api/routers/auth.py). Two screens loading at the
    // same moment is the ordinary case, not a corner one, so a second refresh here
    // would log the owner out for real.
    let refreshes = 0
    const fetchMock = vi.fn<typeof fetch>().mockImplementation((input) => {
      const url = input instanceof Request ? input.url : String(input)
      if (url.endsWith('/api/auth/refresh')) {
        refreshes += 1
        return Promise.resolve(new Response(null, { status: 200 }))
      }
      return Promise.resolve(refreshes === 0 ? unauthenticated() : json(ME))
    })
    vi.stubGlobal('fetch', fetchMock)

    const [a, b] = await Promise.all([
      unwrap(api.GET('/api/auth/me', { baseUrl: BASE })),
      unwrap(api.GET('/api/customers', { baseUrl: BASE })),
    ])

    expect(refreshes).toBe(1)
    expect(a).toMatchObject({ email: 'titolare@studio.it' })
    expect(b).toBeTruthy()
  })

  it('gives up after a failed refresh, surfacing "unauthenticated" and no retry', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(unauthenticated())
      .mockResolvedValueOnce(unauthenticated())
    vi.stubGlobal('fetch', fetchMock)

    // What AuthProvider's `me` query sees on the login page: it catches this and
    // renders the login form. One refresh attempt, then the truth -- never a loop.
    await expect(unwrap(api.GET('/api/auth/me', { baseUrl: BASE }))).rejects.toMatchObject({
      code: 'unauthenticated',
      status: 401,
    })
    expect(urls(fetchMock)).toEqual([`${BASE}/api/auth/me`, '/api/auth/refresh'])
  })

  it('surfaces a 401 from the retry itself instead of refreshing again', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(unauthenticated())
      .mockResolvedValueOnce(new Response(null, { status: 200 }))
      .mockResolvedValueOnce(unauthenticated())
    vi.stubGlobal('fetch', fetchMock)

    await expect(unwrap(api.GET('/api/auth/me', { baseUrl: BASE }))).rejects.toMatchObject({
      code: 'unauthenticated',
    })
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it.each([
    ['/api/auth/login' as const, { email: 'a@b.it', password: 'x' }],
    ['/api/auth/logout' as const, undefined],
    ['/api/auth/refresh' as const, undefined],
  ])('never refreshes for %s, whose own 401 is the answer', async (path, body) => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(unauthenticated())
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      unwrap(api.POST(path, { baseUrl: BASE, body } as never)),
    ).rejects.toMatchObject({ code: 'unauthenticated' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('never refreshes a request that carries its own Bearer credential', async () => {
    // A personal access token is not the session cookie: there is nothing to
    // renew, and the caller (a script, an integration) owns its own credential.
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(unauthenticated())
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      unwrap(
        api.GET('/api/auth/me', { baseUrl: BASE, headers: { Authorization: 'Bearer pat_abc' } }),
      ),
    ).rejects.toMatchObject({ code: 'unauthenticated' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('replays the same method and body, byte for byte, on the retry', async () => {
    // `fetch` consumes a request's body stream, so the retry cannot re-send the
    // request that already went out: a copy has to be taken while it is intact.
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(unauthenticated())
      .mockResolvedValueOnce(new Response(null, { status: 200 }))
      .mockResolvedValueOnce(json({ id: 'c1' }))
    vi.stubGlobal('fetch', fetchMock)

    const body = { ragione_sociale: 'Rossi SRL', nazione: 'IT', custom_fields: {} }
    await unwrap(api.POST('/api/customers', { baseUrl: BASE, body }))

    const [first, , retried] = fetchMock.mock.calls.map(([input]) => input as Request)
    expect(retried?.method).toBe('POST')
    expect(retried?.url).toBe(first?.url)
    expect(retried?.headers.get('Content-Type')).toBe('application/json')
    expect(await retried!.text()).toBe(JSON.stringify(body))
    expect(await first!.text()).toBe(JSON.stringify(body))
  })
})

/** The one multipart upload cannot go through the typed client either (openapi-fetch
 *  has no way to send a `FormData` body for a multipart route), so it shares the
 *  downloads' `fetchWithRefresh` -- same fifteen-minute cliff, same fix. */
describe('fetchWithRefresh with a FormData body', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('re-sends the very same FormData on the retry', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(null, { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 201 }))
    vi.stubGlobal('fetch', fetchMock)

    const form = new FormData()
    form.append('file', new Blob(['contenuto']), 'contratto.pdf')
    const response = await fetchWithRefresh('/api/documents/d1/versions', {
      method: 'POST',
      body: form,
    })

    expect(response.status).toBe(201)
    expect(fetchMock.mock.calls[2]?.[1]).toMatchObject({ method: 'POST', body: form })
  })
})
