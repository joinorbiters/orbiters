import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SETTINGS_TABS } from '@/features/settings/tabs'
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
    activeOptions,
  }: {
    children: React.ReactNode
    to: string
    className?: string
    activeProps?: Record<string, unknown>
    activeOptions?: { exact?: boolean }
  }) => {
    // `activeOptions.exact` is honoured, because the shell relies on it: without it "/app"
    // is a prefix of every other route and Home would be the current page everywhere.
    const active = activeOptions?.exact
      ? mockRoute.pathname === to
      : mockRoute.pathname === to || mockRoute.pathname.startsWith(`${to}/`)
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
  // A fresh element on every call: re-rendering the *same* element object is a React
  // bail-out, which would make `refresh()` (the stand-in for a navigation) do nothing.
  const tree = () => (
    <QueryClientProvider client={client}>
      <AppShell>{children}</AppShell>
    </QueryClientProvider>
  )
  const result = render(tree())
  return { ...result, refresh: () => result.rerender(tree()) }
}

/**
 * jsdom has no layout, so the breakpoint the shell reads has to be stated. Desktop is the
 * default here because it is the layout most of these assertions are about; the two
 * below-`lg` tests set it themselves.
 */
function setViewport(desktop: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: desktop && query.includes('min-width'),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

function sidebar() {
  return within(screen.getByRole('navigation', { name: 'Navigazione principale' }))
}

beforeEach(() => {
  setViewport(true)
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

  it('lists one sub-item per settings tab, in the same order', async () => {
    // Against the shared `SETTINGS_TABS` and not against a handful of labels typed out
    // here: a tab added to the settings page and forgotten in the sidebar is exactly the
    // drift this list exists to prevent.
    renderShell()
    await userEvent.click(sidebar().getByRole('button', { name: 'Impostazioni' }))
    const subItems = sidebar()
      .getAllByRole('link')
      .filter((link) => link.getAttribute('href')?.startsWith('/app/impostazioni/'))
    expect(subItems.map((link) => link.textContent)).toEqual(
      SETTINGS_TABS.map((tab) => tab.label),
    )
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

  it('draws a focus ring the dark sidebar can actually show', () => {
    // shadcn's Button sets `outline-none` and a Watermelon/50 ring, which over Prussian
    // Blue is 1.73:1 -- i.e. no visible focus at all. Every control in here asks for
    // `--sidebar-ring` (Paper) instead.
    renderShell()
    expect(sidebar().getByRole('link', { name: 'Home' })).toHaveClass(
      'focus-visible:ring-sidebar-ring',
    )
    expect(screen.getByRole('button', { name: 'Comprimi il menu' })).toHaveClass(
      'focus-visible:ring-sidebar-ring',
    )
  })

  it('is a rail below lg, whose expanded form is an overlay you can dismiss', async () => {
    // 272px of the 390px a phone has is not a layout, it is a menu.
    setViewport(false)
    renderShell()
    expect(sidebar().queryByRole('button', { name: 'Vendite' })).not.toBeInTheDocument()
    expect(sidebar().getByRole('link', { name: 'Clienti' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Espandi il menu' }))
    expect(sidebar().getByRole('button', { name: 'Vendite' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Chiudi il menu' }))
    expect(sidebar().queryByRole('button', { name: 'Vendite' })).not.toBeInTheDocument()
  })

  it('closes the overlay when the route changes, so it never covers the page you asked for', async () => {
    setViewport(false)
    const { refresh } = renderShell()
    await userEvent.click(screen.getByRole('button', { name: 'Espandi il menu' }))
    expect(sidebar().getByRole('button', { name: 'Vendite' })).toBeInTheDocument()

    mockRoute.pathname = '/app/ore'
    refresh()
    expect(sidebar().queryByRole('button', { name: 'Vendite' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Chiudi il menu' })).not.toBeInTheDocument()
  })

  it('has no overlay on a desktop viewport: the sidebar is a column beside the page', async () => {
    renderShell()
    await userEvent.click(screen.getByRole('button', { name: 'Comprimi il menu' }))
    expect(screen.queryByRole('button', { name: 'Chiudi il menu' })).not.toBeInTheDocument()
    expect(sidebar().getByRole('link', { name: 'Impostazioni' })).toBeInTheDocument()
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
