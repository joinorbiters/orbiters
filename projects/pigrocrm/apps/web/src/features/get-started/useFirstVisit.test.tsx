/** The Home's one-time redirect to «Get started» (ORB-180). */
import { render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useFirstVisitGoesToGetStarted } from './useFirstVisit'

const navigate = vi.fn()
vi.mock('@tanstack/react-router', () => ({ useNavigate: () => navigate }))

const auth = { user: { id: 'u1' } as { id: string } | null }
vi.mock('@/lib/auth', () => ({ useAuth: () => ({ user: auth.user }) }))

function Home() {
  useFirstVisitGoesToGetStarted()
  return <p>home</p>
}

beforeEach(() => navigate.mockReset())
afterEach(() => {
  window.localStorage.clear()
  auth.user = { id: 'u1' }
})

describe('the first visit', () => {
  it('goes to Get started once, with a replace, and not the next time', () => {
    render(<Home />)
    expect(navigate).toHaveBeenCalledWith({ to: '/app/get-started', replace: true })
    window.localStorage.setItem('pigrocrm.get-started.visto:/:u1', '1')
    navigate.mockReset()
    render(<Home />)
    expect(navigate).not.toHaveBeenCalled()
  })

  it('does nothing while nobody is logged in', () => {
    auth.user = null
    render(<Home />)
    expect(navigate).not.toHaveBeenCalled()
  })

  it('remembers per user: another account in the same browser is taken there too', () => {
    window.localStorage.setItem('pigrocrm.get-started.visto:/:u1', '1')
    auth.user = { id: 'u2' }
    render(<Home />)
    expect(navigate).toHaveBeenCalledWith({ to: '/app/get-started', replace: true })
  })
})
