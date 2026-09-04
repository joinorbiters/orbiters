import { Link, Outlet, useRouterState } from '@tanstack/react-router'
import { ShieldAlert } from 'lucide-react'
import { defaultDashboardSearch } from '@/features/dashboard/search'
import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useIsAdmin } from '@/lib/auth'

const TABS = [
  { value: 'campi', label: 'Campi' },
  { value: 'pipeline', label: 'Pipeline' },
  { value: 'template', label: 'Template' },
  { value: 'emittente', label: 'Emittente' },
  { value: 'fiscale', label: 'Fiscale' },
  { value: 'utenti', label: 'Utenti' },
  { value: 'categorie-costo', label: 'Categorie costo' },
  { value: 'tariffe', label: 'Tariffe' },
  { value: 'periodi', label: 'Periodi' },
  { value: 'gmail', label: 'Gmail' },
  { value: 'drive', label: 'Google Drive' },
  { value: 'automazioni', label: 'Automazioni' },
] as const

/**
 * Campi/Pipeline/Template/Emittente/Utenti are admin-only at the service layer
 * (`FieldDefinitionService`/`PipelineService`/`TemplateService`/
 * `EmitterProfileService`/`UserService` all call `actor.require_admin` on every
 * write) -- Token is not (`PatService` scopes by `actor.id`, not role) and lives
 * at its own route, `/app/token`, outside this gate entirely.
 *
 * Note the asymmetry on the two newest: `TemplateService.list`/`describe`/
 * `preview` and `EmitterProfileService.get` carry no role check, because the
 * new-from-template dialog and the PDF header need them for every role. Only the
 * writes are gated, and only the writes live behind this tab.
 *
 * The three slice-4 tabs are gated the same way and for the same reason:
 * `CostCategoryService` and `PeriodLockService` call `actor.require_admin` on every
 * write, and so do `update_user_rates` and `update_deal_rate`. All four are also
 * deliberately absent from the MCP surface, so this gate is the explanation of why
 * they are here and never the thing that enforces it.
 *
 * `useIsAdmin` reads the session `AuthProvider` already cached -- no extra
 * request -- and this reads it *before* rendering `<Outlet />`, not in a
 * `useEffect` that would let a first render mount the children regardless.
 * `routes/app.tsx`'s own guard already blocks reaching this component at all
 * until the session has resolved, so there is no separate loading state to
 * account for here. A non-admin gets an explanation in place, never a silent
 * redirect.
 *
 * Lives here, not in `routes/app/impostazioni.tsx` itself, so it can be
 * imported by a plain component test (`SettingsLayout.test.tsx`) the same way
 * every other component in this codebase is -- a route file exporting
 * anything beyond `Route` also opts that route out of the router plugin's
 * automatic code-splitting, which a `routeTree.gen.ts` warning caught
 * directly while wiring this test up.
 */
export function SettingsLayout() {
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
            stato della pipeline o un nuovo utente, chiedi a un amministratore del tuo account.
          </p>
          <Button asChild variant="outline" className="mt-2">
            {/* Since slice 6 `/app/` declares `validateSearch`, so its search params are
                part of its type and a `<Link to="/app">` without them does not compile.
                This link has no period of its own in mind, which is exactly what
                `defaultDashboardSearch()` answers -- and sending the resolved month rather
                than an empty object means the address bar is true from the first paint,
                which is the whole reason §4 put the period in the URL. */}
            <Link to="/app" search={defaultDashboardSearch()}>
              Torna alla dashboard
            </Link>
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
