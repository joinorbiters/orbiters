import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider, useIsAdmin } from './auth'
import { api } from './api'

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  return { ...actual, api: { ...actual.api, GET: vi.fn(), POST: vi.fn() } }
})

function ok(data: unknown) {
  return { data, response: new Response(null, { status: 200 }) } as never
}

const ADMIN = { id: 'u1', email: 'a@p.it', nome: 'Admin', ruolo: 'admin', attivo: true }
const DEMOTED = { ...ADMIN, ruolo: 'collaboratore' }

function Probe() {
  const isAdmin = useIsAdmin()
  return <div>{isAdmin ? 'admin' : 'not-admin'}</div>
}

function renderProbe() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(api.GET).mockReset()
  // `shouldAdvanceTime` keeps real wall-clock progress ticking the fake clock
  // forward too -- without it, @testing-library's own `findBy*`/`waitFor`
  // polling (built on `setTimeout`) never sees time pass at all and every
  // `await screen.findByText(...)` below hangs until vitest's own test
  // timeout, never react-query's `refetchInterval`.
  vi.useFakeTimers({ shouldAdvanceTime: true })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('AuthProvider — session freshness', () => {
  /**
   * Fix-round item 5: `useIsAdmin`/`useCanWrite` read this same cached `me`
   * value, so without a periodic refetch, a role change or deactivation made
   * from another session only reached an already-open tab on its next full
   * reload -- the tab kept rendering every admin screen, and kept letting the
   * user try admin actions the backend would refuse, for as long as they
   * stayed on the page. This proves the poll actually happens and actually
   * updates what `useIsAdmin` reports, not merely that a `refetchInterval`
   * option is present in the source.
   */
  it('re-reads the session periodically, so a demotion made elsewhere is reflected without a reload', async () => {
    vi.mocked(api.GET).mockReturnValueOnce(Promise.resolve(ok(ADMIN)))
    renderProbe()
    expect(await screen.findByText('admin')).toBeInTheDocument()

    vi.mocked(api.GET).mockReturnValueOnce(Promise.resolve(ok(DEMOTED)))
    await vi.advanceTimersByTimeAsync(30_000)

    expect(await screen.findByText('not-admin')).toBeInTheDocument()
  })

  it('does not poll before a session exists, so the login page does not hammer the endpoint pre-auth', async () => {
    vi.mocked(api.GET).mockReturnValue(
      Promise.resolve({ error: { detail: 'Autenticazione richiesta' }, response: new Response(null, { status: 401 }) } as never),
    )
    renderProbe()
    await screen.findByText('not-admin')

    await vi.advanceTimersByTimeAsync(60_000)

    // One fetch for the initial (failed, "not authenticated") load; the
    // `refetchInterval` guard (`query.state.data ? 30_000 : false`) is what
    // keeps a `null` session from being polled at all.
    expect(api.GET).toHaveBeenCalledTimes(1)
  })
})
