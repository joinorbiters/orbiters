import { Link, Outlet, createFileRoute, useRouterState } from '@tanstack/react-router'
import { ShieldAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useIsAdmin } from '@/lib/auth'

const TABS = [
  { value: 'campi', label: 'Campi' },
  { value: 'pipeline', label: 'Pipeline' },
  { value: 'utenti', label: 'Utenti' },
  { value: 'token', label: 'Token' },
] as const

/**
 * Every write these four tabs offer is admin-only at the service layer
 * (`FieldDefinitionService.create/update/archive/unarchive`,
 * `PipelineService.create/update/delete/seed_defaults`, `UserService.create/
 * update/list` all call `actor.require_admin`) -- confirmed by reading each
 * service directly, not assumed from the router. `TokensPanel` is the one
 * exception on the backend (`PatService` scopes by `actor.id`, not role: any
 * authenticated user can manage their own tokens), but it stays behind this same
 * gate for this slice, matching the brief's own framing of PATs as part of "the
 * admin side" of the product alongside fields, pipeline and users.
 *
 * Without a guard here, a `collaboratore`/`readonly` session that opens this URL
 * (typed directly, or a stale bookmark -- `AppShell`'s nav never offers it to
 * begin with, see its own `isAdmin &&` check) would mount all four panels, each
 * firing its own list/create query on render, and watch every single one of
 * them resolve as a 403. `useIsAdmin` reads the session already cached by
 * `AuthProvider` (the `GET /api/auth/me` response) -- no extra request -- and
 * this component reads it *before* ever rendering `<Outlet />`, not in a
 * `useEffect` that fires after a first render has already mounted the children.
 * That ordering is the actual fix: the parent route (`routes/app.tsx`) already
 * blocks rendering *this* component at all until the session has resolved
 * (`isLoading`/`!user` both return early there), so by the time this runs,
 * `isAdmin` is already a settled, correct boolean -- there is no further loading
 * state to account for here, and no window where the four panels can mount and
 * fire a request before the check has a verdict.
 *
 * A non-admin who lands here still gets an explanation in place, not a silent
 * `navigate()` elsewhere -- the brief's own `SettingsLayout` did exactly that
 * (a `useEffect` redirect racing against an unconditional `<Outlet />`), which
 * is a "bare bounce" even when it works: nothing on screen says why they ended
 * up back on the dashboard.
 */
function SettingsLayout() {
  const isAdmin = useIsAdmin()
  const { location } = useRouterState()

  if (!isAdmin) {
    return (
      <div className="p-8">
        <div className="mx-auto flex max-w-md flex-col items-center gap-3 pt-16 text-center">
          <ShieldAlert className="size-10 text-muted-foreground" aria-hidden="true" />
          <h1 className="text-xl font-semibold tracking-tight">Accesso riservato</h1>
          <p className="text-muted-foreground">
            Le impostazioni sono riservate agli amministratori. Se ti serve un nuovo campo, uno
            stato della pipeline, un utente o un token, chiedi a un amministratore del tuo
            account.
          </p>
          <Button asChild variant="outline" className="mt-2">
            <Link to="/app">Torna alla dashboard</Link>
          </Button>
        </div>
      </div>
    )
  }

  const active = TABS.find((tab) => location.pathname.endsWith(tab.value))?.value ?? 'campi'

  return (
    <div className="p-8">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Impostazioni</h1>
      <Tabs value={active}>
        <TabsList>
          {TABS.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value} asChild>
              <Link to={`/app/impostazioni/${tab.value}`}>{tab.label}</Link>
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <div className="mt-6">
        <Outlet />
      </div>
    </div>
  )
}

export const Route = createFileRoute('/app/impostazioni')({ component: SettingsLayout })
