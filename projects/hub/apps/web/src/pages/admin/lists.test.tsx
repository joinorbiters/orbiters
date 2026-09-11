import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  Outlet,
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AdminFreelancerDetail, AdminFreelancers, AdminSignups } from './lists'

function answer(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

/** A card the admin wrote from a signup (ORB-155): no CV, no rate, no position, no
 *  remote preference, and the attribution that says so. */
const INCOMPLETE = {
  id: 'f1',
  nome: 'Ada',
  cognome: 'Lovelace',
  email: 'ada@studio.it',
  linkedin_url: 'https://www.linkedin.com/in/ada',
  cv_filename: null,
  cv_size: null,
  tariffa_giornaliera: null,
  posizione: null,
  remoto: null,
  links: ['https://github.com/ada'],
  stato: 'nuovo',
  note: null,
  utm_source: 'linkedin',
  utm_campaign: null,
  created_at: '2026-09-10T10:00:00Z',
  compilata_da: 'admin',
  completa: false,
  commenti: [],
}

const COMPLETE = {
  ...INCOMPLETE,
  id: 'f2',
  nome: 'Grace',
  cognome: 'Hopper',
  email: 'grace@studio.it',
  cv_filename: 'Grace CV.pdf',
  cv_size: 2048,
  tariffa_giornaliera: '500.00',
  posizione: 'CTO',
  remoto: 'remoto',
  compilata_da: 'persona',
  completa: true,
}

const SIGNUPS = [
  {
    id: 's1',
    email: 'ada@studio.it',
    nome: 'Ada',
    cognome: 'Lovelace',
    linkedin_url: 'https://www.linkedin.com/in/ada',
    utm_source: 'linkedin',
    created_at: '2026-09-09T10:00:00Z',
    freelancer_id: 'f1',
  },
  {
    id: 's2',
    email: 'bob@example.org',
    nome: 'Bob',
    cognome: 'Ross',
    linkedin_url: 'https://www.linkedin.com/in/bob',
    utm_source: 'newsletter',
    created_at: '2026-09-08T10:00:00Z',
    freelancer_id: null,
  },
]

/** The admin routes the three pages sit on, without the layout and its guard: the
 *  pages read `useParams` and render `Link`s, so a router has to be there. */
function mount(path: string) {
  const root = createRootRoute({ component: () => <Outlet /> })
  const iscrizioni = createRoute({ getParentRoute: () => root, path: '/admin/iscrizioni', component: AdminSignups })
  const freelance = createRoute({ getParentRoute: () => root, path: '/admin/freelance', component: AdminFreelancers })
  const detail = createRoute({
    getParentRoute: () => root,
    path: '/admin/freelance/$id',
    component: AdminFreelancerDetail,
  })
  const router = createRouter({
    routeTree: root.addChildren([iscrizioni, freelance, detail]),
    history: createMemoryHistory({ initialEntries: [path] }),
  })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

/** The cell under a given column header, so a «—» is checked where it is expected and
 *  not anywhere on the row. */
function cellUnder(row: HTMLElement, header: string): HTMLElement {
  const table = row.closest('table')!
  const headers = within(table).getAllByRole('columnheader').map((cell) => cell.textContent)
  const index = headers.indexOf(header)
  expect(index).toBeGreaterThanOrEqual(0)
  return within(row).getAllByRole('cell')[index]!
}

afterEach(() => vi.restoreAllMocks())

describe('the Iscrizioni page', () => {
  it('links a signup to its card when one exists, and prints a dash otherwise', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(answer(200, { totale: 2, iscrizioni: SIGNUPS }))
    mount('/admin/iscrizioni')
    const ada = (await screen.findByText('ada@studio.it')).closest('tr')!
    const link = within(cellUnder(ada, 'Scheda')).getByRole('link', { name: 'apri' })
    expect(link.getAttribute('href')).toMatch(/\/f1$/)

    const bob = screen.getByText('bob@example.org').closest('tr')!
    expect(cellUnder(bob, 'Scheda')).toHaveTextContent('—')
    expect(within(cellUnder(bob, 'Scheda')).queryByRole('link')).toBeNull()
  })
})

describe('the Developer e CTO list', () => {
  it('renders an incomplete card with dashes and a «Da completare» pill', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(answer(200, { totale: 2, items: [INCOMPLETE, COMPLETE] }))
    mount('/admin/freelance')
    const ada = (await screen.findByText('ada@studio.it')).closest('tr')!
    expect(cellUnder(ada, 'Posizione')).toHaveTextContent('—')
    expect(cellUnder(ada, 'Tariffa')).toHaveTextContent('—')
    expect(cellUnder(ada, 'Dove')).toHaveTextContent('—')
    expect(within(cellUnder(ada, 'Stato')).getByText('Nuovo')).toBeInTheDocument()
    expect(within(cellUnder(ada, 'Stato')).getByText('Da completare')).toBeInTheDocument()

    const grace = screen.getByText('grace@studio.it').closest('tr')!
    expect(cellUnder(grace, 'Posizione')).toHaveTextContent('CTO')
    expect(cellUnder(grace, 'Tariffa')).toHaveTextContent('500,00')
    expect(cellUnder(grace, 'Dove')).toHaveTextContent('Da remoto')
    expect(within(grace).queryByText('Da completare')).toBeNull()
  })
})

describe('the freelancer detail', () => {
  it('shows an incomplete card without a CV link and says the admin wrote it', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(answer(200, INCOMPLETE))
    mount('/admin/freelance/f1')
    await screen.findByRole('heading', { name: 'Ada Lovelace' })
    expect(spy.mock.calls[0]![0]).toBe('/api/hub/freelancers/f1')
    expect(screen.queryByRole('link', { name: /CV/ })).toBeNull()
    expect(screen.getByText('Da completare')).toBeInTheDocument()
    expect(screen.getByText('scritta dall’admin, da completare')).toBeInTheDocument()
    // The three answers the person has not given yet read as dashes, not as a crash.
    const rows = screen.getAllByRole('definition')
    expect(rows.filter((row) => row.textContent === '—').length).toBeGreaterThanOrEqual(3)
  })

  it('shows a complete card with its CV and says the person filled it in', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(answer(200, COMPLETE))
    mount('/admin/freelance/f2')
    await screen.findByRole('heading', { name: 'Grace Hopper' })
    expect(screen.getByRole('link', { name: /CV/ })).toHaveAttribute('href', '/api/hub/freelancers/f2/cv')
    expect(screen.queryByText('Da completare')).toBeNull()
    expect(screen.getByText('compilata dalla persona')).toBeInTheDocument()
    expect(screen.getByText('Da remoto')).toBeInTheDocument()
  })
})
