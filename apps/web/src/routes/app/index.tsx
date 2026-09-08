import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { DashboardPage } from '@/features/dashboard/DashboardPage'
import { validateDashboardSearch, type DashboardSearch } from '@/features/dashboard/search'

/**
 * The dashboard, with its period in the URL.
 *
 * The first route in this codebase with `validateSearch` -- list filters everywhere else
 * are component-local `useState`. The period is in the URL because a screenshot or a shared
 * link of a dashboard with no explicit period is a number with no unit (§4).
 *
 * Only `Route` is exported: anything else opts this route out of the router plugin's
 * automatic code-splitting. The page itself is `features/dashboard/DashboardPage.tsx` and
 * the validator `features/dashboard/search.ts`, both so they can be tested directly.
 */
function DashboardRoute() {
  const search = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  // No `PageHeader` here: `DashboardPage` draws its own, because the tabs and the period
  // belong in it (§4) and they are what this component would otherwise have to reach
  // into the page for. The route's whole job is the URL round trip.
  return (
    <DashboardPage
      search={search}
      // Merged into the existing search rather than replacing it, so changing the tab
      // keeps the period and changing the period keeps the tab.
      onSearchChange={(next: Partial<DashboardSearch>) =>
        void navigate({ search: (previous) => ({ ...previous, ...next }) })
      }
    />
  )
}

export const Route = createFileRoute('/app/')({
  validateSearch: validateDashboardSearch,
  component: DashboardRoute,
})
