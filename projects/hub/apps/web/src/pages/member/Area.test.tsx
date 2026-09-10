import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  Outlet,
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Area } from './Area'
import { MemberGuard } from './Guard'

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

afterEach(() => vi.restoreAllMocks())

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
    expect(screen.getByText('Altro in arrivo')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Modifica' })).toHaveAttribute('href', '/io/modifica')
  })

  it('sends a visitor without a session to /accedi', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(answer(401, { detail: 'Autenticazione richiesta' }))
    mount()
    expect(await screen.findByRole('heading', { name: 'Accedi' })).toBeInTheDocument()
  })
})
