import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  Outlet,
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Area } from './Area'
import { MemberGuard } from './Guard'

vi.mock('@orbiters/analytics/browser', () => ({
  capture: vi.fn(),
  identifyUser: vi.fn(),
  resetUser: vi.fn(),
}))
import { capture, identifyUser, resetUser } from '@orbiters/analytics/browser'

function answer(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const PROFILE = {
  id: 'f1',
  nome: 'Ada',
  cognome: 'Lovelace',
  email: 'ada@studio.it',
  linkedin_url: 'https://www.linkedin.com/in/ada',
  cv_filename: 'Ada CV.pdf',
  cv_size: 2048,
  tariffa_giornaliera: '450.00',
  posizione: 'Backend developer',
  remoto: 'ibrido',
  links: ['https://github.com/ada'],
  created_at: '2026-09-10T10:00:00Z',
  updated_at: '2026-09-10T10:00:00Z',
  completa: true,
}

/** The card an admin wrote from Ada's signup (ORB-155): the person has yet to add the
 *  CV, the rate, the position and how she works. */
const INCOMPLETE = {
  ...PROFILE,
  cv_filename: null,
  cv_size: null,
  tariffa_giornaliera: null,
  posizione: null,
  remoto: null,
  completa: false,
}

function mount() {
  const root = createRootRoute({ component: () => <Outlet /> })
  const io = createRoute({ getParentRoute: () => root, path: '/io', component: MemberGuard })
  const index = createRoute({ getParentRoute: () => io, path: '/', component: Area })
  const accedi = createRoute({ getParentRoute: () => root, path: '/accedi', component: () => <h1>Accedi</h1> })
  const router = createRouter({
    routeTree: root.addChildren([io.addChildren([index]), accedi]),
    history: createMemoryHistory({ initialEntries: ['/io'] }),
  })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.clearAllMocks()
})

describe('/io', () => {
  it('shows the answers under the wizard’s questions, the CV and the two perks', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(answer(200, PROFILE))
    mount()
    // The name is both the heading and the answer to the first question.
    expect(await screen.findAllByText('Ada Lovelace')).not.toHaveLength(0)
    expect(screen.getByText('Come ti chiami?')).toBeInTheDocument()
    expect(screen.getByText('450.00 € / giorno')).toBeInTheDocument()
    expect(screen.getByText('Ibrido')).toBeInTheDocument()
    expect(screen.getByText('ada@studio.it')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Ada CV\.pdf/ })).toHaveAttribute('href', '/api/hub/me/cv')
    expect(screen.getByRole('link', { name: /Apri PigroCRM/ })).toHaveAttribute(
      'href',
      'https://pigro.joinorbiters.com/app/registrati',
    )
    expect(screen.getByRole('link', { name: /Scarica la guida/ })).toHaveAttribute(
      'href',
      '/api/hub/me/guida',
    )
    expect(screen.getByText('PDF, 6 pagine, 48 KB.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Modifica' })).toHaveAttribute('href', '/io/modifica')
    // A complete card gets no reminder.
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.queryByText('Nessun CV')).toBeNull()
  })

  it('asks the person to complete a card the admin wrote, and shows no CV link', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(answer(200, INCOMPLETE))
    mount()
    const notice = await screen.findByRole('status')
    expect(notice).toHaveTextContent('La tua scheda è incompleta.')
    expect(within(notice).getByRole('link', { name: 'Completa la scheda' })).toHaveAttribute('href', '/io/modifica')
    expect(screen.getByText('Nessun CV')).toBeInTheDocument()
    expect(screen.getAllByRole('link').some((link) => link.getAttribute('href') === '/api/hub/me/cv')).toBe(false)
    // The unanswered questions read as dashes, not as a crash.
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(3)
  })

  it('sends a visitor without a session to /accedi', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(answer(401, { detail: 'Autenticazione richiesta' }))
    mount()
    expect(await screen.findByRole('heading', { name: 'Accedi' })).toBeInTheDocument()
    expect(identifyUser).not.toHaveBeenCalled()
  })
})

describe('what the area reports to PostHog (ORB-185)', () => {
  it('identifies the member once the profile is known, by id, with the email and the name', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(answer(200, PROFILE))
    mount()
    await screen.findAllByText('Ada Lovelace')
    expect(identifyUser).toHaveBeenCalledTimes(1)
    expect(identifyUser).toHaveBeenCalledWith('f1', { email: 'ada@studio.it', nome: 'Ada' })
  })

  it('counts the guide on the click and leaves the download to the link', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(answer(200, PROFILE))
    mount()
    const link = await screen.findByRole('link', { name: /Scarica la guida/ })
    // jsdom cannot navigate; stopping the default here does not stop React's own handler.
    link.addEventListener('click', (event) => event.preventDefault())
    await userEvent.setup().click(link)
    expect(capture).toHaveBeenCalledWith('guida_scaricata')
    expect(link).toHaveAttribute('href', '/api/hub/me/guida')
  })

  it('forgets the person on Esci, before the page leaves', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(answer(200, PROFILE))
    // The logout ends in `window.location.assign`, which jsdom cannot do and says so
    // once on the console (from its own console, out of a spy's reach); the assertion
    // is about what happens before it.
    mount()
    await screen.findAllByText('Ada Lovelace')
    await userEvent.setup().click(screen.getByRole('button', { name: /Esci/ }))
    await waitFor(() => expect(resetUser).toHaveBeenCalledTimes(1))
  })
})
