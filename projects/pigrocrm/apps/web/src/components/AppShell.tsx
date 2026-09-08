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
import { SETTINGS_TABS, type SettingsTabValue } from '@/features/settings/tabs'
import { useMediaQuery } from '@/hooks/use-media-query'
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
 *
 * Below `lg` the sidebar is the icon rail by default and its expanded form is an overlay
 * over the page, dismissed by a backdrop or by navigating: 272px of the 390px a phone has
 * would leave the content about 118px, which is not a layout. Above `lg` it is the column
 * beside the page, collapsible to the same rail as before.
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
 * «Impostazioni», whose sub-items are the settings tabs -- one per entry of the shared
 * `SETTINGS_TABS`, so the sidebar cannot drift from the page that renders them.
 *
 * Its own constant, separate from `GROUPS`, because it behaves differently in two ways:
 * it is admin-only (every service behind these tabs calls `actor.require_admin` on every
 * write), and in the collapsed rail it becomes a single icon link -- thirteen icons for
 * the tabs of one page would be a rail of settings and nothing else.
 */
/**
 * One literal path per settings tab. `satisfies Record<SettingsTabValue, ...>` is what
 * makes this exhaustive: adding a tab to `SETTINGS_TABS` without a route here is a
 * compile error, which is the whole point of keeping the labels in one place and the
 * paths in the place that can typecheck them.
 */
const SETTINGS_PATHS = {
  spazio: '/app/impostazioni/spazio',
  campi: '/app/impostazioni/campi',
  pipeline: '/app/impostazioni/pipeline',
  template: '/app/impostazioni/template',
  emittente: '/app/impostazioni/emittente',
  fiscale: '/app/impostazioni/fiscale',
  utenti: '/app/impostazioni/utenti',
  'categorie-costo': '/app/impostazioni/categorie-costo',
  tariffe: '/app/impostazioni/tariffe',
  periodi: '/app/impostazioni/periodi',
  gmail: '/app/impostazioni/gmail',
  drive: '/app/impostazioni/drive',
  automazioni: '/app/impostazioni/automazioni',
} as const satisfies Record<SettingsTabValue, string>

const SETTINGS = {
  id: 'impostazioni',
  label: 'Impostazioni',
  icon: Settings,
  base: '/app/impostazioni',
  items: SETTINGS_TABS.map((tab) => ({ to: SETTINGS_PATHS[tab.value], label: tab.label })),
} as const

/**
 * Every path the sidebar links to, as a union of literals: that is what makes
 * `<Link to={item.to}>` check against the generated route tree at all, and what would
 * fail to compile the day one of these routes is renamed.
 */
type LinkTo =
  | (typeof TOP_LEVEL)[number]['to']
  | (typeof GROUPS)[number]['items'][number]['to']
  | (typeof SETTINGS_PATHS)[SettingsTabValue]

// `metaKey` on Apple platforms, `ctrlKey` elsewhere. Read once at module scope from the
// platform hint rather than sniffing the user agent string: this only decides which glyph
// is drawn, and the palette's listener accepts either modifier regardless.
const IS_APPLE =
  typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform ?? '')

/**
 * The focus ring of every control in here, on every one of them.
 *
 * `--sidebar-ring` is Paper (see `tokens.css`), not the app-wide `--ring`: Watermelon at
 * 50% over Prussian Blue is 1.73:1, which is a ring nobody can see -- and shadcn's
 * `Button` sets `outline-none`, so an invisible ring is *no* visible focus at all. The
 * `cn()` here is `twMerge`, so this overrides the ring colour the button variant sets.
 */
const FOCUS =
  'outline-none focus-visible:ring-[3px] focus-visible:ring-sidebar-ring focus-visible:ring-offset-0'

const ITEM = 'flex items-center gap-3 rounded-[10px] px-3 py-2 text-sm transition-colors'
// The active pill: a lighter, translucent fill on the dark sidebar rather than the solid
// Watermelon the flat list used -- with grouped navigation there are two things to mark at
// once (the group and the item inside it), and two solid fills would fight.
const ACTIVE =
  'data-[status=active]:bg-sidebar-accent data-[status=active]:text-sidebar-accent-foreground data-[status=active]:font-medium'
const QUIET = 'text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground'

/** Below this the sidebar is a rail whose expanded form is an overlay, not a column. */
const DESKTOP = '(min-width: 1024px)'

/** Is `pathname` this entry, or a page below it (a detail route, a tab)? */
function matches(pathname: string, to: string, exact = false) {
  return exact ? pathname === to : pathname === to || pathname.startsWith(`${to}/`)
}

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const isAdmin = useIsAdmin()
  const { location } = useRouterState()
  // Below `lg` a 272px sidebar leaves ~118px of page on a 390px phone, so there the
  // sidebar is the rail by default and its expanded form is an overlay over the content.
  // The breakpoint has to be read in JS and not only in CSS because the two are different
  // *structures*, not two widths of one.
  const isDesktop = useMediaQuery(DESKTOP)
  // Local, unpersisted UI state -- collapsing to an icon rail is a per-visit
  // convenience, not a setting worth a round trip or a storage key. Which groups are
  // open *is* stored (see `sidebarGroups.ts`): it is a standing preference about the
  // shape of your own navigation.
  const [collapsed, setCollapsed] = useState(false)
  // The overlay, stored as *where* it was opened rather than as a boolean: navigating
  // closes it, with no effect to synchronise, because the pathname it was opened at is no
  // longer the current one. A menu that stays open over the page you just asked for is
  // the classic mobile-drawer bug.
  const [openedAt, setOpenedAt] = useState<string | null>(null)
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
  // The group holding the current route opens by itself unless you dismissed it in this
  // session: the alternative is a page whose own entry in the sidebar is not on screen,
  // and the alternative to *that* -- nailing it open -- is a chevron that does nothing.
  // The dismissal is deliberately not stored: what gets written is the preference you
  // chose, not what one route did on your behalf, so a reload of the same page opens the
  // group again.
  const [dismissed, setDismissed] = useState<string | undefined>(undefined)
  const isOpen = (id: string) =>
    openGroups[id] === true || (id === activeGroup && dismissed !== id)

  const toggleGroup = (id: string) => {
    const next = { ...openGroups, [id]: !isOpen(id) }
    if (id === activeGroup) setDismissed(isOpen(id) ? id : undefined)
    setOpenGroups(writeSidebarGroups(next))
  }

  // What the sidebar is showing right now, and what the one toggle does to it.
  const overlay = !isDesktop && openedAt === location.pathname
  const expanded = isDesktop ? !collapsed : overlay
  const rail = !expanded
  const toggleSidebar = () =>
    isDesktop
      ? setCollapsed((value) => !value)
      : setOpenedAt(overlay ? null : location.pathname)

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
      className={cn(ITEM, QUIET, ACTIVE, FOCUS, rail && 'justify-center px-0')}
    >
      <Icon className="size-4 shrink-0" aria-hidden="true" />
      <span className={cn('truncate', rail && 'sr-only')}>{label}</span>
    </Link>
  )

  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      {overlay && (
        <>
          {/* A real button, not an `aria-hidden` div: dismissing an overlay is something a
              keyboard has to be able to do, and this is the control that does it. */}
          <button
            type="button"
            aria-label="Chiudi il menu"
            onClick={() => setOpenedAt(null)}
            className="fixed inset-0 z-30 bg-[var(--color-prussian-blue)]/50"
          />
          {/* The rail's own width, kept in the flow while the sidebar itself is out of it,
              so the page underneath does not shift as the overlay opens and closes. */}
          <div aria-hidden="true" className="w-[4.5rem] shrink-0" />
        </>
      )}
      <aside
        className={cn(
          // As tall as the viewport, never as tall as the page: the profile at the bottom
          // is reachable without scrolling, and the navigation scrolls on its own if it
          // ever outgrows the window.
          'flex h-dvh shrink-0 flex-col bg-sidebar text-sidebar-foreground transition-[width] duration-200 ease-linear',
          rail ? 'w-[4.5rem]' : 'w-[17rem]',
          // Below `lg` the expanded sidebar is an overlay over the content, not a column
          // beside it: 272px of the 390px a phone has is not a layout, it is a menu.
          overlay && 'fixed inset-y-0 left-0 z-40 shadow-2xl',
        )}
      >
        <div
          className={cn(
            'flex items-center gap-2 px-4 pt-5 pb-3',
            rail ? 'justify-center' : 'justify-between',
          )}
        >
          <span
            className={cn(
              'inline-flex items-center truncate text-lg font-medium tracking-tight',
              rail && 'sr-only',
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
            className={cn(
              'shrink-0 text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground',
              FOCUS,
            )}
            onClick={toggleSidebar}
            aria-label={rail ? 'Espandi il menu' : 'Comprimi il menu'}
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
              FOCUS,
              rail && 'justify-center px-0',
            )}
          >
            <Search className="size-4 shrink-0" aria-hidden="true" />
            <span className={cn('flex-1 text-left', rail && 'sr-only')}>Cerca</span>
            <kbd
              className={cn(
                'rounded border border-sidebar-border px-1.5 py-0.5 text-xs font-medium',
                rail && 'sr-only',
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

          {rail
            ? // The rail: no headers, no indentation, every section one click away. The
              // settings tabs are the exception -- one link to the page that owns them.
              [
                ...GROUPS.flatMap((group) => group.items.map((item) => leaf(item))),
                ...TOP_LEVEL.slice(1).map((item) => leaf(item)),
                // The first tab, under the group's own name: in the rail the label is the
                // accessible name, and «Spazio» would say nothing about where it goes.
                isAdmin
                  ? leaf({ to: SETTINGS_PATHS.spazio, label: SETTINGS.label, icon: Settings })
                  : null,
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
                  FOCUS,
                  rail && 'justify-center px-0',
                )}
                aria-label="Menu del profilo"
              >
                <Avatar className="size-8 shrink-0">
                  <AvatarFallback className="bg-sidebar-accent text-xs text-sidebar-foreground">
                    {initials}
                  </AvatarFallback>
                </Avatar>
                <div className={cn('min-w-0 flex-1', rail && 'sr-only')}>
                  <p className="truncate text-sm font-medium">{user?.nome}</p>
                  <p className="truncate text-xs text-sidebar-foreground/70">{user?.ruolo}</p>
                </div>
                <ChevronsUpDown
                  className={cn('size-4 shrink-0 text-sidebar-foreground/70', rail && 'hidden')}
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
        className={cn(ITEM, QUIET, FOCUS, 'w-full')}
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
          FOCUS,
        )}
      >
        {label}
      </Link>
    </li>
  )
}
