import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AppShell } from './AppShell'

vi.mock('@tanstack/react-router', () => ({
  Link: ({ children, ...props }: { children: React.ReactNode }) => <a {...props}>{children}</a>,
  useRouterState: () => ({ location: { pathname: '/clienti' } }),
  // The command palette the shell mounts navigates; nothing here asserts on where.
  useNavigate: () => vi.fn(),
}))

const mockAuth = vi.hoisted(() => ({ ruolo: 'admin' as string }))
vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ user: { nome: 'Ivan', email: 'm@example.com', ruolo: mockAuth.ruolo }, logout: vi.fn() }),
  useIsAdmin: () => mockAuth.ruolo === 'admin',
}))

/**
 * The shell mounts the command palette, which is a TanStack Query consumer, so the
 * provider is part of the harness rather than of any one test. Its query is disabled
 * below three characters, so nothing here issues a request.
 */
function renderShell(children: React.ReactNode = <div />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AppShell>{children}</AppShell>
    </QueryClientProvider>,
  )
}

describe('AppShell', () => {
  it('shows the main navigation in Italian', () => {
    renderShell()
    // Scoped to the sidebar: since the header landed, the breadcrumb renders the current
    // section's label too, so an unscoped getByText('Clienti') now matches twice.
    const sidebar = within(screen.getByRole('navigation', { name: 'Navigazione principale' }))
    for (const label of [
      'Dashboard',
      'Clienti',
      'Persone',
      'Deal',
      'Fatture',
      'Analisi',
      'Token',
    ]) {
      expect(sidebar.getByText(label)).toBeInTheDocument()
    }
  })

  it('renders the header with the search control', () => {
    renderShell()
    expect(screen.getByRole('banner')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /cerca/i })).toBeInTheDocument()
  })

  it('opens the search palette from the header button', async () => {
    // The wiring, end to end: the header's button is the only thing that opens the
    // palette for a user who does not know the shortcut.
    renderShell()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /cerca/i }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('shows Impostazioni to an admin', () => {
    mockAuth.ruolo = 'admin'
    renderShell()
    expect(screen.getByText('Impostazioni')).toBeInTheDocument()
  })

  it('hides Impostazioni from a non-admin', () => {
    mockAuth.ruolo = 'collaboratore'
    renderShell()
    expect(screen.queryByText('Impostazioni')).not.toBeInTheDocument()
  })

  /**
   * A personal access token is not an admin setting -- `PatService` scopes it
   * by `actor.id`, not role -- so unlike Impostazioni, this entry must survive
   * for every role. Checked for both non-admin roles the backend has, not
   * just one, since "collaboratore" and "readonly" are two different guard
   * checks that could each independently regress.
   */
  it.each(['collaboratore', 'readonly'])('shows Token to a %s, not just to an admin', (ruolo) => {
    mockAuth.ruolo = ruolo
    renderShell()
    expect(screen.getByText('Token')).toBeInTheDocument()
  })

  it('renders its children', () => {
    renderShell(<p>contenuto</p>)
    expect(screen.getByText('contenuto')).toBeInTheDocument()
  })
})
