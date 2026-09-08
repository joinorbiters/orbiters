import { Link, useRouterState } from '@tanstack/react-router'
import type { LucideIcon } from 'lucide-react'
import {
  Briefcase,
  Building2,
  ChevronDown,
  ChevronsUpDown,
  Clock,
  Handshake,
  KeyRound,
  LayoutDashboard,
  LogOut,
  MailWarning,
  PanelLeftIcon,
  Receipt,
  Search,
  Settings,
  TrendingUp,
  Users,
  Wallet,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { BrandMark } from '@/components/BrandMark'
import { readSidebarGroups, writeSidebarGroups } from '@/components/sidebarGroups'
import { CommandPalette } from '@/features/search/CommandPalette'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useAuth, useIsAdmin } from '@/lib/auth'
import { cn } from '@/lib/utils'

/**
 * The shell of the app: a dark sidebar on the left, everything else in a white panel
 * inset on the Paper background (spec 2026-09-08 §4).
 *
 * Three things moved in this revision. The global search is a field at the top of the
 * sidebar rather than a control in a top bar -- there is no top bar any more, so a page's
 * own `PageHeader` is the first thing inside the panel and owns the title and the primary
 * action. The navigation is grouped instead of flat: nine entries in one column had no
 * reading order left to give, while «Vendite» / «Amministrazione» say what the sections
 * are for. And the content is a panel with its own scroll, so the sidebar and the page
 * header never scroll away.
 *
 * Home is the dashboard, `/app`. Analisi is one link and not a group on purpose: its
 * three screens are tabs of one page, so the sidebar points at the first of them.
 */

// Token is a top-level entry, not one of the settings sub-items below: a personal access
// token belongs to whoever creates it, any role (`PatService` scopes by `actor.id`, not
// role), while the whole «Impostazioni» group is admin-only. Putting it inside that group
// would mean a collaborator could never connect an agent to their own account.
const TOP_LEVEL = [
  { to: '/app', label: 'Home', icon: LayoutDashboard, exact: true },
  // After the two groups in the rendering below, because every figure it reports is
  // derived from what they contain. Not admin-gated: margins and estimate-versus-actual
  // carry no role check at the service layer, and only the fiscal tab inside does --
  // gating the whole entry would hide two ordinary reads to protect a third.
  { to: '/app/analisi/margini', label: 'Analisi', icon: TrendingUp, exact: false },
  { to: '/app/token', label: 'Token', icon: KeyRound, exact: false },
] as const

/**
 * The two collapsible groups. The sub-items carry an icon even though the expanded
 * rendering shows only their label: the icon is what the collapsed rail draws, where
 * these become plain icon links and the group header disappears.
 *
 * «Amministrazione» reads in the order the money is supposed to move: the register, then
 * what an unpaid invoice becomes, then the hours the next invoice is built from. Neither
 * group is admin-gated -- e.g. `SollecitiService.candidates` is a plain read of your own
 * books, and the write behind «Prepara sollecito» is gated at the service, where the
 * refusal belongs.
 */
const GROUPS = [
  {
    id: 'vendite',
    label: 'Vendite',
    icon: Briefcase,
    items: [
      { to: '/app/clienti', label: 'Clienti', icon: Building2 },
      { to: '/app/persone', label: 'Persone', icon: Users },
      { to: '/app/deal', label: 'Deal', icon: Handshake },
    ],
  },
  {
    id: 'amministrazione',
    label: 'Amministrazione',
    icon: Wallet,
    items: [
      { to: '/app/fatture', label: 'Fatture', icon: Receipt },
      { to: '/app/solleciti', label: 'Solleciti', icon: MailWarning },
      { to: '/app/ore', label: 'Ore', icon: Clock },
    ],
  },
] as const

/**
 * «Impostazioni», whose sub-items are the tabs of `features/settings/SettingsLayout.tsx`.
 *
 * The labels are repeated here rather than imported from that module for two reasons: a
 * `<Link to>` needs a literal path to typecheck against the generated route tree, and
 * `SettingsLayout.tsx` is a component file, where a second export would trip
 * `react-refresh/only-export-components`. `SettingsLayout` remains the thing that renders
 * the tabs; this is the sidebar's way in to each of them.
 *
 * Its own constant, separate from `GROUPS`, because it behaves differently in two ways:
 * it is admin-only (every service behind these tabs calls `actor.require_admin` on every
 * write), and in the collapsed rail it becomes a single icon link -- thirteen icons for
 * the tabs of one page would be a rail of settings and nothing else.
 */
const SETTINGS = {
  id: 'impostazioni',
  label: 'Impostazioni',
  icon: Settings,
  base: '/app/impostazioni',
  items: [
    { to: '/app/impostazioni/spazio', label: 'Spazio' },
    { to: '/app/impostazioni/campi', label: 'Campi' },
    { to: '/app/impostazioni/pipeline', label: 'Pipeline' },
    { to: '/app/impostazioni/template', label: 'Template' },
    { to: '/app/impostazioni/emittente', label: 'Emittente' },
    { to: '/app/impostazioni/fiscale', label: 'Fiscale' },
    { to: '/app/impostazioni/utenti', label: 'Utenti' },
    { to: '/app/impostazioni/categorie-costo', label: 'Categorie costo' },
    { to: '/app/impostazioni/tariffe', label: 'Tariffe' },
    { to: '/app/impostazioni/periodi', label: 'Periodi' },
    { to: '/app/impostazioni/gmail', label: 'Gmail' },
    { to: '/app/impostazioni/drive', label: 'Google Drive' },
    { to: '/app/impostazioni/automazioni', label: 'Automazioni' },
  ],
} as const

/**
 * Every path the sidebar links to, as a union of literals: that is what makes
 * `<Link to={item.to}>` check against the generated route tree at all, and what would
 * fail to compile the day one of these routes is renamed.
 */
type LinkTo =
  | (typeof TOP_LEVEL)[number]['to']
  | (typeof GROUPS)[number]['items'][number]['to']
  | (typeof SETTINGS)['items'][number]['to']

// `metaKey` on Apple platforms, `ctrlKey` elsewhere. Read once at module scope from the
// platform hint rather than sniffing the user agent string: this only decides which glyph
// is drawn, and the palette's listener accepts either modifier regardless.
const IS_APPLE =
  typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform ?? '')

const ITEM = 'flex items-center gap-3 rounded-[10px] px-3 py-2 text-sm transition-colors'
// The active pill: a lighter, translucent fill on the dark sidebar rather than the solid
// Watermelon the flat list used -- with grouped navigation there are two things to mark at
// once (the group and the item inside it), and two solid fills would fight.
const ACTIVE = 'data-[status=active]:bg-sidebar-accent data-[status=active]:font-medium'
const QUIET = 'text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground'

/** Is `pathname` this entry, or a page below it (a detail route, a tab)? */
function matches(pathname: string, to: string, exact = false) {
  return exact ? pathname === to : pathname === to || pathname.startsWith(`${to}/`)
}

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const isAdmin = useIsAdmin()
  const { location } = useRouterState()
  // Local, unpersisted UI state -- collapsing to an icon rail is a per-visit
  // convenience, not a setting worth a round trip or a storage key. Which groups are
  // open *is* stored (see `sidebarGroups.ts`): it is a standing preference about the
  // shape of your own navigation.
  const [collapsed, setCollapsed] = useState(false)
  // The palette is mounted here, once, rather than inside the search field: it owns the
  // Cmd/Ctrl+K listener, so it has to be alive even while the field has never been
  // clicked.
  const [searchOpen, setSearchOpen] = useState(false)

  const groups = isAdmin ? [...GROUPS, SETTINGS] : GROUPS
  const activeGroup = groups.find((group) =>
    'base' in group
      ? matches(location.pathname, group.base)
      : group.items.some((item) => matches(location.pathname, item.to)),
  )?.id

  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(readSidebarGroups)
  // The group holding the current route opens by itself, whatever you last left it as:
  // the alternative is a page whose own entry in the sidebar is not on screen. You can
  // still close it -- that is what this remembers, and why the header is a live toggle
  // rather than a chevron that does nothing while you stay inside the group. Not stored:
  // the preference is what you chose deliberately, not what one route did on your behalf.
  const [dismissed, setDismissed] = useState<string | undefined>(undefined)
  const isOpen = (id: string) =>
    openGroups[id] === true || (id === activeGroup && dismissed !== id)

  const toggleGroup = (id: string) => {
    if (id === activeGroup) setDismissed(isOpen(id) ? id : undefined)
    setOpenGroups((previous) => writeSidebarGroups({ ...previous, [id]: !isOpen(id) }))
  }

  const initials = (user?.nome ?? '?')
    .split(' ')
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()

  /** A leaf entry: an icon and a label expanded, an icon alone in the rail. */
  const leaf = ({
    to,
    label,
    icon: Icon,
    exact = false,
  }: {
    to: LinkTo
    label: string
    icon: LucideIcon
    exact?: boolean
  }) => (
    <Link
      key={to}
      to={to}
      activeOptions={{ exact }}
      activeProps={{ 'aria-current': 'page' }}
      className={cn(ITEM, QUIET, ACTIVE, collapsed && 'justify-center px-0')}
    >
      <Icon className="size-4 shrink-0" aria-hidden="true" />
      <span className={cn('truncate', collapsed && 'sr-only')}>{label}</span>
    </Link>
  )

  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      <aside
        className={cn(
          // As tall as the viewport, never as tall as the page: the profile at the bottom
          // is reachable without scrolling, and the navigation scrolls on its own if it
          // ever outgrows the window.
          'flex h-dvh shrink-0 flex-col bg-sidebar text-sidebar-foreground transition-[width] duration-200 ease-linear',
          collapsed ? 'w-[4.5rem]' : 'w-[17rem]',
        )}
      >
        <div
          className={cn(
            'flex items-center gap-2 px-4 pt-5 pb-3',
            collapsed ? 'justify-center' : 'justify-between',
          )}
        >
          <span
            className={cn(
              'inline-flex items-center truncate text-lg font-medium tracking-tight',
              collapsed && 'sr-only',
            )}
          >
            <BrandMark className="mr-2.5" />
            {/* Brand accent, not body text: --color-watermelon (not the AA-adjusted
                -strong variant) is exactly what the design tokens reserve for this. */}
            Pigro<span className="text-[var(--color-watermelon)]">CRM</span>
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            className="shrink-0 text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground"
            onClick={() => setCollapsed((value) => !value)}
            aria-label={collapsed ? 'Espandi il menu' : 'Comprimi il menu'}
          >
            <PanelLeftIcon className="size-4" />
          </Button>
        </div>

        {/* A button that looks like a field, not an <input>: the palette is a dialog, so a
            real text field here would take focus, accept typing, and then hand it over --
            two places to type the same query. One control, one place to type. */}
        <div role="search" className="px-3 pb-3">
          <button
            type="button"
            onClick={() => setSearchOpen(true)}
            aria-label="Cerca in tutto il CRM"
            className={cn(
              'flex w-full items-center gap-2 rounded-[10px] border border-sidebar-border bg-sidebar-accent/50 px-3 py-2 text-sm text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground',
              collapsed && 'justify-center px-0',
            )}
          >
            <Search className="size-4 shrink-0" aria-hidden="true" />
            <span className={cn('flex-1 text-left', collapsed && 'sr-only')}>Cerca</span>
            <kbd
              className={cn(
                'rounded border border-sidebar-border px-1.5 py-0.5 text-xs font-medium',
                collapsed && 'sr-only',
              )}
            >
              {IS_APPLE ? '⌘' : 'Ctrl'} K
            </kbd>
          </button>
        </div>

        {/* Labelled because a page's own header may render a second <nav> landmark (a
            breadcrumb, a set of tabs), and two unlabelled ones are indistinguishable to a
            screen reader -- and to `getByRole('navigation')`. */}
        <nav
          aria-label="Navigazione principale"
          className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 pb-3"
        >
          {leaf(TOP_LEVEL[0])}

          {collapsed
            ? // The rail: no headers, no indentation, every section one click away. The
              // settings tabs are the exception -- one link to the page that owns them.
              [
                ...GROUPS.flatMap((group) => group.items.map((item) => leaf(item))),
                ...TOP_LEVEL.slice(1).map((item) => leaf(item)),
                isAdmin ? leaf({ ...SETTINGS.items[0], label: SETTINGS.label, icon: Settings }) : null,
              ]
            : [
                ...GROUPS.map((group) => (
                  <NavGroup
                    key={group.id}
                    label={group.label}
                    icon={group.icon}
                    open={isOpen(group.id)}
                    onToggle={() => toggleGroup(group.id)}
                  >
                    {group.items.map((item) => subItem(item))}
                  </NavGroup>
                )),
                ...TOP_LEVEL.slice(1).map((item) => leaf(item)),
                isAdmin ? (
                  <NavGroup
                    key={SETTINGS.id}
                    label={SETTINGS.label}
                    icon={SETTINGS.icon}
                    open={isOpen(SETTINGS.id)}
                    onToggle={() => toggleGroup(SETTINGS.id)}
                  >
                    {SETTINGS.items.map((item) => subItem(item))}
                  </NavGroup>
                ) : null,
              ]}
        </nav>

        {/* The profile, anchored at the bottom, opens a menu: the account's own things --
            who is signed in, the space's settings for an admin, the way out. */}
        <div className="mt-auto border-t border-sidebar-border p-3">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className={cn(
                  'flex w-full items-center gap-3 rounded-[10px] px-2 py-2 text-left transition-colors hover:bg-sidebar-accent',
                  collapsed && 'justify-center px-0',
                )}
                aria-label="Menu del profilo"
              >
                <Avatar className="size-8 shrink-0">
                  <AvatarFallback className="bg-sidebar-accent text-xs text-sidebar-foreground">
                    {initials}
                  </AvatarFallback>
                </Avatar>
                <div className={cn('min-w-0 flex-1', collapsed && 'sr-only')}>
                  <p className="truncate text-sm font-medium">{user?.nome}</p>
                  <p className="truncate text-xs text-sidebar-foreground/70">{user?.ruolo}</p>
                </div>
                <ChevronsUpDown
                  className={cn('size-4 shrink-0 text-sidebar-foreground/70', collapsed && 'hidden')}
                  aria-hidden="true"
                />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent side="top" align="start" className="w-56">
              <DropdownMenuLabel className="font-normal">
                <p className="truncate text-sm font-medium">{user?.nome}</p>
                <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              {isAdmin && (
                <DropdownMenuItem asChild>
                  <Link to="/app/impostazioni/spazio">
                    <Settings className="size-4" />
                    Impostazioni dello spazio
                  </Link>
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onSelect={() => void logout()}>
                <LogOut className="size-4" />
                Esci
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </aside>

      {/* The content panel: Paper outside, white inside, its own scroll. Below `lg` the
          inset and the radius drop to nothing and the panel simply is the page -- a 12px
          frame around a phone screen is 12px of nothing. */}
      <div className="flex min-w-0 flex-1 flex-col p-0 lg:p-3">
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden border-0 border-border bg-card lg:rounded-2xl lg:border">
          <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
        </div>
      </div>

      <CommandPalette open={searchOpen} onOpenChange={setSearchOpen} />
    </div>
  )
}

/**
 * A group header and, when it is open, its sub-items.
 *
 * `aria-expanded` on a real `<button>` rather than a styled `<div>`: the state of a
 * disclosure is something a screen reader has to be able to read and a keyboard has to be
 * able to change, and both come free this way.
 */
function NavGroup({
  label,
  icon: Icon,
  open,
  onToggle,
  children,
}: {
  label: string
  icon: LucideIcon
  open: boolean
  onToggle: () => void
  children: ReactNode
}) {
  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className={cn(ITEM, QUIET, 'w-full')}
      >
        <Icon className="size-4 shrink-0" aria-hidden="true" />
        <span className="flex-1 truncate text-left">{label}</span>
        <ChevronDown
          className={cn('size-4 shrink-0 transition-transform', !open && '-rotate-90')}
          aria-hidden="true"
        />
      </button>
      {open && (
        // The thin vertical line of the reference: one border on the list, so it runs the
        // height of the sub-items whatever their number.
        <ul className="mt-1 ml-6 space-y-0.5 border-l border-sidebar-border pl-3">{children}</ul>
      )}
    </div>
  )
}

/** A sub-item: label only. The indentation and the line say where it belongs. */
function subItem({ to, label }: { to: LinkTo; label: string }) {
  return (
    <li key={to}>
      <Link
        to={to}
        activeProps={{ 'aria-current': 'page' }}
        className={cn(
          'block truncate rounded-[10px] px-3 py-1.5 text-sm transition-colors',
          QUIET,
          ACTIVE,
        )}
      >
        {label}
      </Link>
    </li>
  )
}
