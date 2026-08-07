import { Link, useRouterState } from '@tanstack/react-router'
import {
  Building2,
  Handshake,
  LayoutDashboard,
  LogOut,
  PanelLeftIcon,
  Settings,
  Users,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { useAuth, useIsAdmin } from '@/lib/auth'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/app', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/app/clienti', label: 'Clienti', icon: Building2 },
  { to: '/app/persone', label: 'Persone', icon: Users },
  { to: '/app/deal', label: 'Deal', icon: Handshake },
] as const

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const isAdmin = useIsAdmin()
  const { location } = useRouterState()
  // Local, unpersisted UI state -- collapsing to an icon rail is a per-visit
  // convenience, not a setting worth a round trip or a storage key.
  const [collapsed, setCollapsed] = useState(false)

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
          'flex flex-col border-r bg-card transition-[width] duration-200 ease-linear',
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
            className={cn('truncate text-xl font-semibold tracking-tight', collapsed && 'sr-only')}
          >
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

        <nav className="flex-1 space-y-1 px-3">
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
        <div className="flex items-center gap-3 p-4">
          <Avatar className="size-8 shrink-0">
            <AvatarFallback className="text-xs">{initials}</AvatarFallback>
          </Avatar>
          <div className={cn('min-w-0 flex-1', collapsed && 'sr-only')}>
            <p className="truncate text-sm font-medium">{user?.nome}</p>
            <p className="truncate text-xs text-muted-foreground">{user?.ruolo}</p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="shrink-0"
            onClick={() => void logout()}
            aria-label="Esci"
          >
            <LogOut className="size-4" />
          </Button>
        </div>
      </aside>

      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  )
}
