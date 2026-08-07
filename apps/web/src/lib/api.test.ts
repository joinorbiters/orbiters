import { describe, expect, it } from 'vitest'
import { fieldErrorFrom, toProblem, unwrap } from './api'

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

  it('attaches the real HTTP status even to a body that does not embed one', async () => {
    // The exact shape login/me/refresh return for a 401: openapi-fetch's parsed
    // `error` never carries the response's own status code (see api.ts's docstring
    // on unwrap), so without this, queryClient's retry policy could never see 401
    // for the one family of responses that matters most for it.
    const response = new Response(null, { status: 401 })
    await expect(
      unwrap(Promise.resolve({ error: BARE_UNAUTHENTICATED, response })),
    ).rejects.toMatchObject({ status: 401, detail: 'Autenticazione richiesta' })
  })

  it('normalises a network-level failure into a ProblemDetail too, not a raw error', async () => {
    await expect(unwrap(Promise.reject(new TypeError('Failed to fetch')))).rejects.toMatchObject({
      code: 'unknown',
    })
  })
})
