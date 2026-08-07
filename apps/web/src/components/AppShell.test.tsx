import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AppShell } from './AppShell'

vi.mock('@tanstack/react-router', () => ({
  Link: ({ children, ...props }: { children: React.ReactNode }) => <a {...props}>{children}</a>,
  useRouterState: () => ({ location: { pathname: '/clienti' } }),
}))

const mockAuth = vi.hoisted(() => ({ ruolo: 'admin' as string }))
vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ user: { nome: 'Ivan', email: 'someone@example.com', ruolo: mockAuth.ruolo }, logout: vi.fn() }),
  useIsAdmin: () => mockAuth.ruolo === 'admin',
}))

describe('AppShell', () => {
  it('shows the main navigation in Italian', () => {
    render(<AppShell><div /></AppShell>)
    for (const label of ['Dashboard', 'Clienti', 'Persone', 'Deal']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('shows Impostazioni to an admin', () => {
    mockAuth.ruolo = 'admin'
    render(<AppShell><div /></AppShell>)
    expect(screen.getByText('Impostazioni')).toBeInTheDocument()
  })

  it('hides Impostazioni from a non-admin', () => {
    mockAuth.ruolo = 'collaboratore'
    render(<AppShell><div /></AppShell>)
    expect(screen.queryByText('Impostazioni')).not.toBeInTheDocument()
  })

  it('renders its children', () => {
    render(<AppShell><p>contenuto</p></AppShell>)
    expect(screen.getByText('contenuto')).toBeInTheDocument()
  })
})
