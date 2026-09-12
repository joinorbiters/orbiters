/** The Home's one-time redirect to «Get started» (ORB-180). */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { useFirstVisitGoesToGetStarted } from './useFirstVisit'

const navigate = vi.fn()
vi.mock('@tanstack/react-router', () => ({ useNavigate: () => navigate }))

const auth = { user: { id: 'u1' } as { id: string } | null }
vi.mock('@/lib/auth', () => ({ useAuth: () => ({ user: auth.user }) }))

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn() } }
})

const EMPTY_PAGE = { items: [], next_cursor: null }
const FULL_PAGE = { items: [{ id: 'x' }], next_cursor: null }

/** An empty space (nothing done, no token) or one in use (everything done, a token). */
function space(inUse: boolean) {
  vi.mocked(api.GET).mockImplementation(
    ((path: string) =>
      Promise.resolve(
        path === '/api/emitter'
          ? inUse
            ? { data: { ragione_sociale: 'A', partita_iva: '01234567890' }, response: new Response(null, { status: 200 }) }
            : { error: { detail: 'Not Found' }, response: new Response(null, { status: 404 }) }
          : path === '/api/tokens'
            ? { data: inUse ? [{ id: 'k' }] : [], response: new Response(null, { status: 200 }) }
            : { data: inUse ? FULL_PAGE : EMPTY_PAGE, response: new Response(null, { status: 200 }) },
      )) as never,
  )
}

function Home() {
  useFirstVisitGoesToGetStarted()
  return <p>home</p>
}

function renderHome() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <Home />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  navigate.mockReset()
  vi.mocked(api.GET).mockReset()
  space(false)
})
afterEach(() => {
  window.localStorage.clear()
  auth.user = { id: 'u1' }
  vi.restoreAllMocks()
})

describe('the first visit', () => {
  it('goes to Get started once, with a replace, when the space has something left to do', async () => {
    renderHome()
    await waitFor(() => expect(navigate).toHaveBeenCalledWith({ to: '/app/get-started', replace: true }))
    expect(navigate).toHaveBeenCalledTimes(1)
  })

  it('does not go again once the page has been seen, and reads nothing', async () => {
    window.localStorage.setItem('pigrocrm.get-started.visto:/:u1', '1')
    renderHome()
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(navigate).not.toHaveBeenCalled()
    expect(api.GET).not.toHaveBeenCalled()
  })

  it('stays on the Home of a space in use, and remembers that so it never asks again', async () => {
    space(true)
    renderHome()
    await waitFor(() => expect(window.localStorage.getItem('pigrocrm.get-started.visto:/:u1')).toBe('1'))
    expect(navigate).not.toHaveBeenCalled()
  })

  it('does nothing while nobody is logged in', async () => {
    auth.user = null
    renderHome()
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(navigate).not.toHaveBeenCalled()
    expect(api.GET).not.toHaveBeenCalled()
  })

  it('remembers per user: another account in the same browser is taken there too', async () => {
    window.localStorage.setItem('pigrocrm.get-started.visto:/:u1', '1')
    auth.user = { id: 'u2' }
    renderHome()
    await waitFor(() => expect(navigate).toHaveBeenCalledWith({ to: '/app/get-started', replace: true }))
  })

  it('never redirects a browser that refuses storage, so it cannot loop', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    renderHome()
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(navigate).not.toHaveBeenCalled()
  })
})
