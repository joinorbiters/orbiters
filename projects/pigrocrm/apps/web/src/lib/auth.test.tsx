import { identifyGroup, identifyUser, resetUser } from '@orbiters/analytics/browser'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth, useIsAdmin } from './auth'
import { api } from './api'

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  return { ...actual, api: { ...actual.api, GET: vi.fn(), POST: vi.fn() } }
})

vi.mock('@orbiters/analytics/browser', () => ({
  capture: vi.fn(),
  identifyGroup: vi.fn(),
  identifyUser: vi.fn(),
  resetUser: vi.fn(),
}))

function ok(data: unknown) {
  return { data, response: new Response(null, { status: 200 }) } as never
}

const ADMIN = { id: 'u1', email: 'a@p.it', nome: 'Admin', ruolo: 'admin', attivo: true }
const DEMOTED = { ...ADMIN, ruolo: 'collaboratore' }

function Probe() {
  const isAdmin = useIsAdmin()
  const { logout } = useAuth()
  return (
    <div>
      {isAdmin ? 'admin' : 'not-admin'}
      {/* `AppShell` fires `void logout()`; here the rejection is caught so a refused
          logout is asserted on rather than reported as an unhandled one. */}
      <button onClick={() => void logout().catch(() => undefined)}>Esci</button>
    </div>
  )
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
  vi.clearAllMocks()
  vi.mocked(api.GET).mockReset()
  vi.mocked(api.POST).mockReset()
  // `shouldAdvanceTime` keeps real wall-clock progress ticking the fake clock
  // forward too -- without it, @testing-library's own `findBy*`/`waitFor`
  // polling (built on `setTimeout`) never sees time pass at all and every
  // `await screen.findByText(...)` below hangs until vitest's own test
  // timeout, never react-query's `refetchInterval`.
  vi.useFakeTimers({ shouldAdvanceTime: true })
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
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

describe('AuthProvider — who PostHog sees', () => {
  it('identifies the person and the space once the session is known, and not again on every poll', async () => {
    vi.mocked(api.GET).mockReturnValue(Promise.resolve(ok(ADMIN)))
    renderProbe()
    expect(await screen.findByText('admin')).toBeInTheDocument()

    expect(identifyUser).toHaveBeenCalledTimes(1)
    expect(identifyUser).toHaveBeenCalledWith('u1', { email: 'a@p.it', nome: 'Admin', ruolo: 'admin' })
    // jsdom's page lives at `/`, which is the root installation, not a space.
    expect(identifyGroup).toHaveBeenCalledTimes(1)
    expect(identifyGroup).toHaveBeenCalledWith('spazio', 'root')

    // The thirty-second re-read answers the same person as a new object.
    await vi.advanceTimersByTimeAsync(30_000)
    expect(api.GET).toHaveBeenCalledTimes(2)
    expect(identifyUser).toHaveBeenCalledTimes(1)
    expect(identifyGroup).toHaveBeenCalledTimes(1)
  })

  it('identifies nobody while there is no session', async () => {
    vi.mocked(api.GET).mockReturnValue(
      Promise.resolve({ error: { detail: 'Autenticazione richiesta' }, response: new Response(null, { status: 401 }) } as never),
    )
    renderProbe()
    await screen.findByText('not-admin')
    expect(identifyUser).not.toHaveBeenCalled()
    expect(identifyGroup).not.toHaveBeenCalled()
  })

  it('forgets the person on logout, before the page leaves', async () => {
    const assign = vi.fn()
    vi.stubGlobal('location', { pathname: '/', assign })
    vi.mocked(api.GET).mockReturnValue(Promise.resolve(ok(ADMIN)))
    vi.mocked(api.POST).mockReturnValue(Promise.resolve(ok(undefined)))
    renderProbe()
    await screen.findByText('admin')

    fireEvent.click(screen.getByRole('button', { name: 'Esci' }))

    await waitFor(() => expect(assign).toHaveBeenCalledWith('/app/login'))
    expect(resetUser).toHaveBeenCalledTimes(1)
    expect(vi.mocked(resetUser).mock.invocationCallOrder[0]).toBeLessThan(
      assign.mock.invocationCallOrder[0] ?? 0,
    )
  })

  it('forgets the person even when the server refused the logout, as it still leaves', async () => {
    const assign = vi.fn()
    vi.stubGlobal('location', { pathname: '/', assign })
    vi.mocked(api.GET).mockReturnValue(Promise.resolve(ok(ADMIN)))
    // `{ error, response }` rather than a rejected promise: `unwrap` is what throws,
    // as it does against the real client.
    vi.mocked(api.POST).mockReturnValue(
      Promise.resolve({ error: { detail: 'boom' }, response: new Response(null, { status: 500 }) } as never),
    )
    renderProbe()
    await screen.findByText('admin')

    fireEvent.click(screen.getByRole('button', { name: 'Esci' }))

    await waitFor(() => expect(assign).toHaveBeenCalledWith('/app/login'))
    expect(resetUser).toHaveBeenCalledTimes(1)
  })
})
