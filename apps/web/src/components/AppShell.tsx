import { Link, useRouterState } from '@tanstack/react-router'
import {
  Building2,
  Clock,
  Handshake,
  KeyRound,
  LayoutDashboard,
  LogOut,
  MailWarning,
  PanelLeftIcon,
  Receipt,
  Settings,
  TrendingUp,
  Users,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { AppHeader } from '@/components/AppHeader'
import { BrandMark } from '@/components/BrandMark'
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
import { Separator } from '@/components/ui/separator'
import { useAuth, useIsAdmin } from '@/lib/auth'
import { cn } from '@/lib/utils'

// Token is here, unconditionally, not inside the `isAdmin &&` block below:
// a personal access token belongs to whoever creates it, any role (`PatService`
// scopes by `actor.id`, not role) -- gating it to admins would mean a
// collaborator could never connect an agent to their own account.
const NAV = [
  { to: '/app', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/app/clienti', label: 'Clienti', icon: Building2 },
  { to: '/app/persone', label: 'Persone', icon: Users },
  { to: '/app/deal', label: 'Deal', icon: Handshake },
  // Right after Deal, and above Fatture: hours are logged against a deal and are what an
  // invoice is later built from, so the sidebar reads in the order the work happens.
  { to: '/app/ore', label: 'Ore', icon: Clock },
  { to: '/app/fatture', label: 'Fatture', icon: Receipt },
  // Right after Fatture, because a sollecito is what an unpaid one becomes: the list is
  // built by crossing the register against what has been collected, so it reads in the
  // order the money is supposed to move. Not admin-gated -- `SollecitiService.candidates`
  // is a plain read of your own books, and the write behind «Prepara sollecito» is gated
  // at the service, where the refusal belongs.
  { to: '/app/solleciti', label: 'Solleciti', icon: MailWarning },
  // After Fatture, because every figure it reports is derived from what comes before it
  // in this list. Not admin-gated: margins and estimate-versus-actual carry no role check
  // at the service layer, and only the fiscal tab inside does -- gating the whole entry
  // would hide two ordinary reads to protect a third.
  { to: '/app/analisi/margini', label: 'Analisi', icon: TrendingUp },
  { to: '/app/token', label: 'Token', icon: KeyRound },
] as const

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const isAdmin = useIsAdmin()
  const { location } = useRouterState()
  // Local, unpersisted UI state -- collapsing to an icon rail is a per-visit
  // convenience, not a setting worth a round trip or a storage key.
  const [collapsed, setCollapsed] = useState(false)
  // The palette is mounted here, once, rather than inside the header: it owns the
  // Cmd/Ctrl+K listener, so it has to be alive even while the header's button has
  // never been clicked.
  const [searchOpen, setSearchOpen] = useState(false)

  const initials = (user?.nome ?? '?')
    .split(' ')
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()

  return (
    <div className="flex min-h-screen">
      <aside
        className={cn(
          // Sticky and as tall as the viewport, never as tall as the page: the profile
          // at the bottom is reachable without scrolling, and the navigation scrolls
          // on its own if it ever outgrows the window.
          'sticky top-0 flex h-dvh flex-col border-r bg-card transition-[width] duration-200 ease-linear',
          collapsed ? 'w-[4.5rem]' : 'w-60',
        )}
      >
        <div
          className={cn(
            'flex items-center gap-2 px-5 py-6',
            collapsed ? 'justify-center' : 'justify-between',
          )}
        >
          <span
            className={cn(
              'inline-flex items-center truncate text-xl font-medium tracking-tight',
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
            className="shrink-0"
            onClick={() => setCollapsed((value) => !value)}
            aria-label={collapsed ? 'Espandi il menu' : 'Comprimi il menu'}
          >
            <PanelLeftIcon className="size-4" />
          </Button>
        </div>

        {/* Labelled because the header's breadcrumb is a second <nav> landmark on the
            same page, and two unlabelled ones are indistinguishable to a screen reader
            (and to `getByRole('navigation')`). */}
        <nav aria-label="Navigazione principale" className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3">
          {NAV.map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              className={cn(
                'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                location.pathname === to
                  ? // Solid fill + light text needs the AA-compliant --primary
                    // (--color-watermelon-strong), the same slot Button's default
                    // variant uses -- not raw --color-watermelon, which is 4.22:1
                    // with white and fails the 4.5:1 text threshold.
                    'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground',
              )}
            >
              <Icon className="size-4 shrink-0" />
              <span className={cn(collapsed && 'sr-only')}>{label}</span>
            </Link>
          ))}

          {isAdmin && (
            <Link
              to="/app/impostazioni/campi"
              className="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <Settings className="size-4 shrink-0" />
              <span className={cn(collapsed && 'sr-only')}>Impostazioni</span>
            </Link>
          )}
        </nav>

        <Separator />
        {/* The profile, anchored at the bottom, opens a menu: the account's own things --
            who is signed in, the space's settings for an admin, the way out. One control
            where there used to be a name and a bare logout icon. */}
        <div className="mt-auto p-3">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="flex w-full items-center gap-3 px-2 py-2 text-left hover:bg-muted"
                aria-label="Menu del profilo"
              >
                <Avatar className="size-8 shrink-0">
                  <AvatarFallback className="text-xs">{initials}</AvatarFallback>
                </Avatar>
                <div className={cn('min-w-0 flex-1', collapsed && 'sr-only')}>
                  <p className="truncate text-sm font-medium">{user?.nome}</p>
                  <p className="truncate text-xs text-muted-foreground">{user?.ruolo}</p>
                </div>
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

      <div className="flex min-w-0 flex-1 flex-col">
        <AppHeader onOpenSearch={() => setSearchOpen(true)} />
        <main className="flex-1 overflow-auto">{children}</main>
      </div>

      <CommandPalette open={searchOpen} onOpenChange={setSearchOpen} />
    </div>
  )
}
