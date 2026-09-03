import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CommercialTab } from './CommercialTab'
import { EconomicTab } from './EconomicTab'
import { OperationalTab } from './OperationalTab'
import { PeriodPicker } from './PeriodPicker'
import { DASHBOARD_TABS, type DashboardSearch } from './search'

/**
 * Three tabs and a period, all of it driven by the URL.
 *
 * The search object comes in as a prop and every change goes back out through
 * `onSearchChange` rather than into local state, so the route can push it into the URL and
 * a shared link reopens the same dashboard (§4). It also makes the round trip testable
 * without standing up a router: what comes in is what the tab requests, what the controls
 * change is what comes back out.
 *
 * Lives here rather than in `routes/app/index.tsx` for the reason `SettingsLayout` does: a
 * route file exporting anything besides `Route` opts that route out of the router plugin's
 * automatic code-splitting.
 */
export function DashboardPage({
  search,
  onSearchChange,
}: {
  search: DashboardSearch
  onSearchChange: (next: Partial<DashboardSearch>) => void
}) {
  const { tab, da, a } = search

  return (
    <div className="space-y-6 p-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <Tabs value={tab} onValueChange={(next) => onSearchChange({ tab: next as typeof tab })}>
          <TabsList>
            {DASHBOARD_TABS.map((candidate) => (
              <TabsTrigger key={candidate.id} value={candidate.id}>
                {candidate.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        {/* §6: the operational dashboard is the current week and a backlog -- the two
            things that make no sense in the past -- so it takes no period, and a picker
            that changed nothing on screen would be a control that lies. */}
        {tab !== 'operativa' && (
          <PeriodPicker periodo={{ da, a }} onChange={(next) => onSearchChange(next)} />
        )}
      </div>

      {/* One tab is mounted at a time, deliberately. Rendering all three and hiding two
          would issue three requests -- three snapshot transactions, each holding two
          pooled connections on the API side -- to draw one screen. §17's placeholders that
          stood here until 6C landed are gone: both dashboards exist now, so a paragraph
          explaining their absence would be the untrue thing on the page. */}
      {tab === 'commerciale' && <CommercialTab periodo={{ da, a }} />}
      {tab === 'economica' && <EconomicTab periodo={{ da, a }} />}
      {/* No period: §6's dashboard is the current week and a backlog. */}
      {tab === 'operativa' && <OperationalTab />}
    </div>
  )
}
