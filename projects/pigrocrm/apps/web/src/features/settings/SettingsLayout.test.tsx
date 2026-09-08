import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SettingsLayout } from './SettingsLayout'

const mockAuth = vi.hoisted(() => ({ isAdmin: true }))
vi.mock('@/lib/auth', () => ({ useIsAdmin: () => mockAuth.isAdmin }))

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return {
    ...actual,
    Link: ({ children, to, ...props }: { children: React.ReactNode; to?: string }) => (
      <a href={to} {...props}>
        {children}
      </a>
    ),
    Outlet: () => <div data-testid="outlet-content" />,
    useRouterState: () => ({ location: { pathname: '/app/impostazioni/campi' } }),
  }
})

describe('SettingsLayout (the /app/impostazioni route guard)', () => {
  it('opens with its title as the page heading, from PageHeader', () => {
    // The shell has had no top bar since the 2026-09-08 revision, so the page's own
    // `<h1>` is the only thing naming the screen.
    mockAuth.isAdmin = true
    render(<SettingsLayout />)
    expect(screen.getByRole('heading', { level: 1, name: 'Impostazioni' })).toBeInTheDocument()
  })

  it('renders the tabs and the active child route for an admin', () => {
    mockAuth.isAdmin = true
    render(<SettingsLayout />)
    expect(screen.getByRole('tab', { name: 'Campi' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Pipeline' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Utenti' })).toBeInTheDocument()
    expect(screen.getByTestId('outlet-content')).toBeInTheDocument()
  })

  /**
   * The three slice-4 tabs. They are asserted here and not only in their own panel
   * tests because a panel that renders correctly but is unreachable is not shipped:
   * every service behind them is admin-only, so this list is the only door they have.
   */
  it('offers the time-tracking settings tabs to an admin', () => {
    mockAuth.isAdmin = true
    render(<SettingsLayout />)
    expect(screen.getByRole('tab', { name: 'Categorie costo' })).toHaveAttribute(
      'href',
      '/app/impostazioni/categorie-costo',
    )
    expect(screen.getByRole('tab', { name: 'Tariffe' })).toHaveAttribute(
      'href',
      '/app/impostazioni/tariffe',
    )
    expect(screen.getByRole('tab', { name: 'Periodi' })).toHaveAttribute(
      'href',
      '/app/impostazioni/periodi',
    )
  })

  /**
   * Same reason as the tabs above: `AutomationsPanel` is the only surface where the two
   * automation rules can be switched at all, and `AutomationConfigService` gates its write
   * on `require_admin`, so this list is the only door it has. A panel with its own passing
   * tests and no way in is not shipped.
   */
  it('offers the automations settings tab to an admin', () => {
    mockAuth.isAdmin = true
    render(<SettingsLayout />)
    expect(screen.getByRole('tab', { name: 'Automazioni' })).toHaveAttribute(
      'href',
      '/app/impostazioni/automazioni',
    )
  })

  it('no longer offers a Token tab here — it moved to its own, non-admin-gated route', () => {
    mockAuth.isAdmin = true
    render(<SettingsLayout />)
    expect(screen.queryByRole('tab', { name: 'Token' })).not.toBeInTheDocument()
  })

  /**
   * This task's second named gap, and the reason a fix round called out that
   * it had no test at all: without this, a collaboratore/readonly session
   * that opens this URL directly mounts every admin panel, each firing its
   * own query that comes back 403. Asserting `Outlet` never renders is the
   * one check that actually rules that out -- asserting the message alone
   * would still pass if the panels rendered invisibly behind it.
   */
  it('shows "Accesso riservato" and never renders the child route for a non-admin', () => {
    mockAuth.isAdmin = false
    render(<SettingsLayout />)
    expect(screen.getByText('Accesso riservato')).toBeInTheDocument()
    expect(screen.queryByTestId('outlet-content')).not.toBeInTheDocument()
    expect(screen.queryByRole('tab')).not.toBeInTheDocument()
  })

  it('gives a non-admin a way back to the dashboard, not a silent bounce', () => {
    mockAuth.isAdmin = false
    render(<SettingsLayout />)
    expect(screen.getByRole('link', { name: 'Torna alla dashboard' })).toHaveAttribute(
      'href',
      '/app',
    )
  })

  it('no longer tells a non-admin they need an admin for a token, since they don’t', () => {
    mockAuth.isAdmin = false
    render(<SettingsLayout />)
    expect(screen.queryByText(/token/i)).not.toBeInTheDocument()
  })
})
