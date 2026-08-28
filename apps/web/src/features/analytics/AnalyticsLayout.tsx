import { Link, Outlet, useRouterState } from '@tanstack/react-router'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

const TABS = [
  { value: 'margini', label: 'Margini' },
  { value: 'preventivo-consuntivo', label: 'Preventivo/consuntivo' },
  { value: 'fiscale', label: 'Fiscale' },
] as const

/**
 * Lives here rather than in `routes/app/analisi.tsx` so it can be imported by a plain
 * component test -- a route file exporting anything beyond `Route` opts that route out
 * of the router plugin's automatic code-splitting, which `routeTree.gen.ts` warns about.
 * The same reason `SettingsLayout` sits in `features/settings/`.
 *
 * No `useIsAdmin` gate on the layout, unlike `SettingsLayout`: Margini and
 * Preventivo/consuntivo are ordinary reads available to any authenticated actor -- the
 * services behind them carry no role check, because a deal's margin is not more
 * sensitive than the deal, the hours and the invoices it is derived from. Only the
 * fiscal estimate is admin-only, enforced by `AnalyticsService.get_fiscal_estimate`, and
 * that panel surfaces the refusal as the server worded it rather than hiding the tab: an
 * explanation beats a feature that appears not to exist.
 */
export function AnalyticsLayout() {
  const { location } = useRouterState()
  const active = TABS.find((tab) => location.pathname.endsWith(tab.value))?.value ?? 'margini'

  return (
    <div className="p-8">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Analisi</h1>
      <Tabs value={active}>
        <TabsList>
          {TABS.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value} asChild>
              <Link to={`/app/analisi/${tab.value}`}>{tab.label}</Link>
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
