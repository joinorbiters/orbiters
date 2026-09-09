import {
  Outlet,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import { Shell } from '@/components/Shell'
import { Chooser } from '@/pages/Chooser'
import { CompanyWizard } from '@/pages/CompanyWizard'
import { FreelancerWizard } from '@/pages/FreelancerWizard'
import { Thanks } from '@/pages/Thanks'
import { AdminLayout } from '@/pages/admin/AdminLayout'
import { AdminLogin } from '@/pages/admin/Login'
import {
  AdminCompanies,
  AdminCompanyDetail,
  AdminFreelancerDetail,
  AdminFreelancers,
  AdminSignups,
} from '@/pages/admin/lists'

/**
 * The route tree, in code: nine screens is not enough to want a file-based router and
 * a generated tree beside it. The public pages sit in the `Shell`; the admin area
 * brings its own frame and its own guard (`AdminLayout`).
 */
const root = createRootRoute({ component: () => <Outlet /> })

const publicLayout = createRoute({
  getParentRoute: () => root,
  id: 'public',
  component: () => (
    <Shell>
      <Outlet />
    </Shell>
  ),
})

const chooser = createRoute({ getParentRoute: () => publicLayout, path: '/', component: Chooser })
const freelance = createRoute({
  getParentRoute: () => publicLayout,
  path: '/freelance',
  component: FreelancerWizard,
})
const aziende = createRoute({
  getParentRoute: () => publicLayout,
  path: '/aziende',
  component: CompanyWizard,
})
const grazie = createRoute({
  getParentRoute: () => publicLayout,
  path: '/grazie',
  validateSearch: (search: Record<string, unknown>): { chi: 'freelance' | 'azienda' } => ({
    chi: search.chi === 'azienda' ? 'azienda' : 'freelance',
  }),
  component: Thanks,
})

const adminLogin = createRoute({ getParentRoute: () => root, path: '/admin/login', component: AdminLogin })
const adminArea = createRoute({ getParentRoute: () => root, path: '/admin', component: AdminLayout })
const adminFreelance = createRoute({
  getParentRoute: () => adminArea,
  path: '/freelance',
  component: AdminFreelancers,
})
const adminFreelanceDetail = createRoute({
  getParentRoute: () => adminArea,
  path: '/freelance/$id',
  component: AdminFreelancerDetail,
})
const adminAziende = createRoute({ getParentRoute: () => adminArea, path: '/aziende', component: AdminCompanies })
const adminAziendeDetail = createRoute({
  getParentRoute: () => adminArea,
  path: '/aziende/$id',
  component: AdminCompanyDetail,
})
const adminIscrizioni = createRoute({
  getParentRoute: () => adminArea,
  path: '/iscrizioni',
  component: AdminSignups,
})

const routeTree = root.addChildren([
  publicLayout.addChildren([chooser, freelance, aziende, grazie]),
  adminLogin,
  adminArea.addChildren([adminFreelance, adminFreelanceDetail, adminAziende, adminAziendeDetail, adminIscrizioni]),
])

export const router = createRouter({ routeTree, basepath: '/hub' })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
