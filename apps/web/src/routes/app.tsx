import { Outlet, createFileRoute, useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'
import { AppShell } from '@/components/AppShell'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/auth'

function AppLayout() {
  const { user, isLoading } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (!isLoading && !user) void navigate({ to: '/login' })
  }, [isLoading, user, navigate])

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
// "/app" a real, matchable path for routes/index.tsx to redirect to and for
// AppShell's nav links to point at.
export const Route = createFileRoute('/app')({ component: AppLayout })
