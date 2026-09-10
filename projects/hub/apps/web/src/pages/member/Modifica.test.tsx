import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  Outlet,
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EDIT_STEPS, Modifica } from './Modifica'

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
  linkedin_url: null,
  cv_filename: 'Ada CV.pdf',
  cv_size: 2048,
  tariffa_giornaliera: '450.00',
  posizione: 'Backend developer',
  remoto: 'remoto',
  links: [],
  created_at: '2026-09-10T10:00:00Z',
  updated_at: '2026-09-10T10:00:00Z',
}

function mount() {
  const root = createRootRoute({ component: () => <Outlet /> })
  const modifica = createRoute({ getParentRoute: () => root, path: '/io/modifica', component: Modifica })
  const io = createRoute({ getParentRoute: () => root, path: '/io', component: () => <h1>La tua area</h1> })
  const router = createRouter({
    routeTree: root.addChildren([modifica, io]),
    history: createMemoryHistory({ initialEntries: ['/io/modifica'] }),
  })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('the edit steps', () => {
  const base = { ...PROFILE, linkedin_url: '', cv: null }

  it('leave the email out and make the CV optional', () => {
    expect(EDIT_STEPS.map((step) => step.id)).not.toContain('email')
    const cv = EDIT_STEPS.find((step) => step.id === 'cv')!
    expect(cv.validate(base as never)).toBeNull()
    const png = new File(['x'], 'cv.png', { type: 'image/png' })
    expect(cv.validate({ ...base, cv: png } as never)).not.toBeNull()
  })

  it('keep the wizard’s rules for everything else', () => {
    const linkedin = EDIT_STEPS.find((step) => step.id === 'linkedin_url')!
    expect(linkedin.validate({ ...base, linkedin_url: 'https://twitter.com/ada' } as never)).not.toBeNull()
  })
})

describe('/io/modifica', () => {
  it('starts from the current answers and saves them with PATCH', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(async (_url, init) =>
        init?.method === 'PATCH'
          ? answer(200, { ...PROFILE, posizione: 'Staff engineer' })
          : answer(200, PROFILE),
      )
    mount()
    const user = userEvent.setup()
    const posizione = await screen.findByLabelText('Posizione')
    expect(posizione).toHaveValue('Backend developer')
    await user.clear(posizione)
    await user.type(posizione, 'Staff engineer')
    await user.click(screen.getByRole('button', { name: 'Salva' }))
    await screen.findByRole('heading', { name: 'La tua area' })
    const patch = fetchSpy.mock.calls.find(([, init]) => init?.method === 'PATCH')!
    expect(patch[0]).toBe('/api/hub/me')
    expect(JSON.parse(patch[1]!.body as string)).toEqual({
      nome: 'Ada',
      cognome: 'Lovelace',
      linkedin_url: null,
      tariffa_giornaliera: '450.00',
      posizione: 'Staff engineer',
      remoto: 'remoto',
      links: [],
    })
    expect(fetchSpy.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(false)
  })

  it('shows a server refusal under the field it names', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_url, init) =>
      init?.method === 'PATCH'
        ? answer(422, {
            detail: [{ loc: ['body', 'tariffa_giornaliera'], msg: 'serve una cifra più bassa' }],
          })
        : answer(200, PROFILE),
    )
    mount()
    const user = userEvent.setup()
    await screen.findByLabelText('Posizione')
    await user.click(screen.getByRole('button', { name: 'Salva' }))
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('serve una cifra più bassa'),
    )
  })

  it('says the rest was saved when only the CV is refused', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_url, init) => {
      if (init?.method === 'PATCH') return answer(200, PROFILE)
      if (init?.method === 'PUT') {
        return answer(422, { detail: [{ loc: ['body', 'cv'], msg: 'il CV deve essere un PDF' }] })
      }
      return answer(200, PROFILE)
    })
    mount()
    const user = userEvent.setup()
    await screen.findByLabelText('Posizione')
    await user.upload(
      screen.getByLabelText('CV'),
      new File(['%PDF'], 'cv.pdf', { type: 'application/pdf' }),
    )
    await user.click(screen.getByRole('button', { name: 'Salva' }))
    await waitFor(() => {
      const alert = screen.getByRole('alert')
      expect(alert).toHaveTextContent('il CV deve essere un PDF')
      expect(alert).toHaveTextContent('Le altre risposte sono salvate')
    })
    expect(screen.getByRole('button', { name: 'Salva' })).toBeInTheDocument()
  })
})
