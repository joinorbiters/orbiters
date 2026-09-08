import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AppShell } from './AppShell'
import { SIDEBAR_GROUPS_KEY } from './sidebarGroups'

const mockRoute = vi.hoisted(() => ({ pathname: '/app/clienti' }))

/**
 * `Link` is substituted rather than mounted in a router, as everywhere else in this
 * codebase -- but the substitute now has to honour `activeProps`, because that is how the
 * sidebar marks the current page (`aria-current="page"`) and a mock that dropped it would
 * make the assertion below pass or fail for the wrong reason.
 */
vi.mock('@tanstack/react-router', () => ({
  Link: ({
    children,
    to,
    className,
    activeProps,
  }: {
    children: React.ReactNode
    to: string
    className?: string
    activeProps?: Record<string, unknown>
  }) => {
    // `activeOptions` is deliberately dropped: the shell asks for an exact match only on
    // "/app", which this substitute gets right by never treating "/app" as a prefix.
    const active =
      mockRoute.pathname === to || (to !== '/app' && mockRoute.pathname.startsWith(`${to}/`))
    return (
      <a href={to} className={className} {...(active ? activeProps : {})}>
        {children}
      </a>
    )
  },
  useRouterState: () => ({ location: { pathname: mockRoute.pathname } }),
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

function sidebar() {
  return within(screen.getByRole('navigation', { name: 'Navigazione principale' }))
}

beforeEach(() => {
  mockAuth.ruolo = 'admin'
  mockRoute.pathname = '/app/clienti'
  localStorage.clear()
})

describe('AppShell', () => {
  it('shows the top-level entries and the group headers in Italian', () => {
    renderShell()
    const nav = sidebar()
    for (const label of ['Home', 'Analisi', 'Token']) {
      expect(nav.getByRole('link', { name: label })).toBeInTheDocument()
    }
    for (const label of ['Vendite', 'Amministrazione', 'Impostazioni']) {
      expect(nav.getByRole('button', { name: label })).toBeInTheDocument()
    }
  })

  it('offers the global search in the sidebar, with the shortcut visible', () => {
    renderShell()
    const search = screen.getByRole('button', { name: /cerca/i })
    expect(search).toBeInTheDocument()
    // Spec §4: the search field sits under the brand and shows its shortcut, so it is
    // discoverable without trying the keyboard.
    expect(search).toHaveTextContent(/K/)
  })

  it('opens the search palette from the sidebar field', async () => {
    renderShell()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /cerca/i }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('opens the group that contains the current route and marks the sub-item', () => {
    renderShell()
    const nav = sidebar()
    expect(nav.getByRole('button', { name: 'Vendite' })).toHaveAttribute('aria-expanded', 'true')
    expect(nav.getByRole('link', { name: 'Clienti' })).toHaveAttribute('aria-current', 'page')
    // A detail page under the section keeps the section marked, which is why the
    // sub-item is matched by prefix and not by equality.
    expect(nav.getByRole('link', { name: 'Persone' })).not.toHaveAttribute('aria-current')
  })

  it('keeps the other groups closed, with their sub-items out of the DOM', () => {
    renderShell()
    const nav = sidebar()
    expect(nav.getByRole('button', { name: 'Amministrazione' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    expect(nav.queryByRole('link', { name: 'Fatture' })).not.toBeInTheDocument()
  })

  it('opens a group on click and persists it', async () => {
    const { unmount } = renderShell()
    await userEvent.click(sidebar().getByRole('button', { name: 'Amministrazione' }))
    expect(sidebar().getByRole('link', { name: 'Solleciti' })).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem(SIDEBAR_GROUPS_KEY) ?? '{}')).toMatchObject({
      amministrazione: true,
    })

    // Persisted means it survives a reload, not just a re-render.
    unmount()
    renderShell()
    expect(sidebar().getByRole('button', { name: 'Amministrazione' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    expect(sidebar().getByRole('link', { name: 'Solleciti' })).toBeInTheDocument()
  })

  it('closes a group on a second click and persists that too', async () => {
    localStorage.setItem(SIDEBAR_GROUPS_KEY, JSON.stringify({ amministrazione: true }))
    renderShell()
    await userEvent.click(sidebar().getByRole('button', { name: 'Amministrazione' }))
    expect(sidebar().queryByRole('link', { name: 'Ore' })).not.toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem(SIDEBAR_GROUPS_KEY) ?? '{}')).toMatchObject({
      amministrazione: false,
    })
  })

  it('lets you close the group of the current route, so the chevron is never a no-op', async () => {
    // The route opens its own group, but it does not nail it open: a header whose
    // aria-expanded cannot change is a control that lies about being one.
    renderShell()
    await userEvent.click(sidebar().getByRole('button', { name: 'Vendite' }))
    expect(sidebar().getByRole('button', { name: 'Vendite' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    expect(sidebar().queryByRole('link', { name: 'Clienti' })).not.toBeInTheDocument()
  })

  it('survives a corrupt stored preference', () => {
    localStorage.setItem(SIDEBAR_GROUPS_KEY, 'non è json')
    renderShell()
    expect(sidebar().getByRole('button', { name: 'Amministrazione' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
  })

  it('lists the settings tabs as the sub-items of Impostazioni', async () => {
    renderShell()
    await userEvent.click(sidebar().getByRole('button', { name: 'Impostazioni' }))
    const nav = sidebar()
    for (const label of ['Spazio', 'Campi', 'Pipeline', 'Utenti', 'Google Drive']) {
      expect(nav.getByRole('link', { name: label })).toBeInTheDocument()
    }
  })

  it('opens Impostazioni when the current route is one of its tabs', () => {
    mockRoute.pathname = '/app/impostazioni/tariffe'
    renderShell()
    const nav = sidebar()
    expect(nav.getByRole('button', { name: 'Impostazioni' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    expect(nav.getByRole('link', { name: 'Tariffe' })).toHaveAttribute('aria-current', 'page')
  })

  it('hides Impostazioni from a non-admin', () => {
    mockAuth.ruolo = 'collaboratore'
    renderShell()
    expect(sidebar().queryByRole('button', { name: 'Impostazioni' })).not.toBeInTheDocument()
  })

  /**
   * A personal access token is not an admin setting -- `PatService` scopes it by
   * `actor.id`, not role -- so unlike Impostazioni it stays a top-level entry, outside the
   * admin-gated group. Checked for both non-admin roles the backend has, since
   * "collaboratore" and "readonly" are two different guard checks that could each
   * independently regress.
   */
  it.each(['collaboratore', 'readonly'])('shows Token to a %s, not just to an admin', (ruolo) => {
    mockAuth.ruolo = ruolo
    renderShell()
    expect(sidebar().getByRole('link', { name: 'Token' })).toBeInTheDocument()
  })

  it('collapses to an icon rail: no group headers, every section still one click away', async () => {
    renderShell()
    await userEvent.click(screen.getByRole('button', { name: 'Comprimi il menu' }))
    const nav = sidebar()
    expect(nav.queryByRole('button', { name: 'Vendite' })).not.toBeInTheDocument()
    // The sub-items of the collapsible groups become icon links in the rail...
    for (const label of ['Home', 'Clienti', 'Deal', 'Fatture', 'Ore', 'Analisi', 'Token']) {
      expect(nav.getByRole('link', { name: label })).toBeInTheDocument()
    }
    // ...except the settings tabs, which are tabs of one page and collapse to one link.
    expect(nav.getByRole('link', { name: 'Impostazioni' })).toBeInTheDocument()
    expect(nav.queryByRole('link', { name: 'Campi' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Espandi il menu' })).toBeInTheDocument()
  })

  it('renders its children inside the content panel', () => {
    renderShell(<p>contenuto</p>)
    expect(within(screen.getByRole('main')).getByText('contenuto')).toBeInTheDocument()
  })

  it('keeps the profile menu', async () => {
    renderShell()
    await userEvent.click(screen.getByRole('button', { name: 'Menu del profilo' }))
    expect(await screen.findByRole('menuitem', { name: /esci/i })).toBeInTheDocument()
  })
})
