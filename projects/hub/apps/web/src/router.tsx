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
import { AdminAdmins } from '@/pages/admin/Admins'
import { AdminLogin } from '@/pages/admin/Login'
import {
  AdminCompanies,
  AdminCompanyDetail,
  AdminFreelancerDetail,
  AdminFreelancers,
  AdminSignups,
} from '@/pages/admin/lists'
import { Accedi } from '@/pages/member/Accedi'
import { Area } from '@/pages/member/Area'
import { Entra } from '@/pages/member/Entra'
import { MemberGuard } from '@/pages/member/Guard'
import { Modifica } from '@/pages/member/Modifica'

/**
 * The route tree, in code: eleven screens is not enough to want a file-based router and
 * a generated tree beside it. The public pages sit in the `Shell`, the chooser alone in
 * a `Shell` without its panel (ORB-128); the admin area brings its own frame and its
 * own guard (`AdminLayout`).
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

const bareLayout = createRoute({
  getParentRoute: () => root,
  id: 'bare',
  component: () => (
    <Shell panel={false}>
      <Outlet />
    </Shell>
  ),
})

const chooser = createRoute({ getParentRoute: () => bareLayout, path: '/', component: Chooser })
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
const accedi = createRoute({ getParentRoute: () => publicLayout, path: '/accedi', component: Accedi })
const entra = createRoute({
  getParentRoute: () => publicLayout,
  path: '/entra',
  validateSearch: (search: Record<string, unknown>): { t: string } => ({
    t: typeof search.t === 'string' ? search.t : '',
  }),
  component: Entra,
})

const io = createRoute({ getParentRoute: () => publicLayout, path: '/io', component: MemberGuard })
const ioIndex = createRoute({ getParentRoute: () => io, path: '/', component: Area })
const ioModifica = createRoute({ getParentRoute: () => io, path: '/modifica', component: Modifica })

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
const adminAmministratori = createRoute({
  getParentRoute: () => adminArea,
  path: '/amministratori',
  component: AdminAdmins,
})

const routeTree = root.addChildren([
  bareLayout.addChildren([chooser]),
  publicLayout.addChildren([
    freelance,
    aziende,
    grazie,
    accedi,
    entra,
    io.addChildren([ioIndex, ioModifica]),
  ]),
  adminLogin,
  adminArea.addChildren([
    adminFreelance,
    adminFreelanceDetail,
    adminAziende,
    adminAziendeDetail,
    adminIscrizioni,
    adminAmministratori,
  ]),
])

export const router = createRouter({ routeTree, basepath: '/hub' })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
