import { Outlet, createFileRoute, useLocation, useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'
import { AppShell } from '@/components/AppShell'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/auth'

function AppLayout() {
  const { user, isLoading } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  // Task A7 moved the login page to routes/app/login.tsx so its URL is
  // /app/login, which makes it a CHILD of this very layout route in TanStack
  // Router's file-based nesting (confirmed in routeTree.gen.ts:
  // AppLoginRoute's getParentRoute is AppRoute) -- rendered inside this
  // component's own <Outlet />. Gating that Outlet on `user` the same way as
  // every other /app/* page would mean an unauthenticated visitor can never
  // see the login form at all: the redirect target and the thing being
  // redirected FROM would be the same gate, chosen forever. The login route is
  // the one child of this layout that must render unconditionally, with no
  // redirect and no AppShell chrome around it.
  const isLoginRoute = pathname === '/app/login'

  useEffect(() => {
    if (!isLoginRoute && !isLoading && !user) void navigate({ to: '/app/login' })
  }, [isLoginRoute, isLoading, user, navigate])

  if (isLoginRoute) return <Outlet />

  if (isLoading) {
    return (
      <div className="space-y-4 p-8">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }
  if (!user) return null

  return (
    <AppShell>
      <Outlet />
    </AppShell>
  )
}

// Deliberately NOT "_app.tsx" (TanStack Router's pathless-layout convention):
// a leading underscore contributes no URL segment at all, so "_app/index.tsx"
// would resolve to the exact same full path as the root "/" -- reproduced live
// while wiring this up ("Conflicting configuration paths ... '/', '/' ...
// routes/index.tsx and routes/_app/index.tsx"). This file's name is what makes
// "/app" a real, matchable path for AppShell's nav links to point at, and for
// nginx's `location = /app { return 302 /app/; }` (deploy/nginx/spa.conf) to
// redirect into. "/" itself belongs to the landing page (apps/web/landing/),
// not to this router at all, since slice 5 (Task A7): there is no more
// routes/index.tsx to redirect from.
export const Route = createFileRoute('/app')({ component: AppLayout })
