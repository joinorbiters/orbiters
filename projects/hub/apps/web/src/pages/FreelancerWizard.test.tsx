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
import { FREELANCER_STEPS, FreelancerWizard, readPerk } from './FreelancerWizard'

/** The wizard mounted on its own little router, so `navigate` has somewhere to go. */
function mount(path = '/freelance?utm_source=linkedin&da=pigrocrm') {
  const root = createRootRoute({ component: () => <Outlet /> })
  const freelance = createRoute({ getParentRoute: () => root, path: '/freelance', component: FreelancerWizard })
  const grazie = createRoute({
    getParentRoute: () => root,
    path: '/grazie',
    validateSearch: (s: Record<string, unknown>) => ({ chi: String(s.chi ?? '') }),
    component: () => <h1>Grazie</h1>,
  })
  const router = createRouter({
    routeTree: root.addChildren([freelance, grazie]),
    history: createMemoryHistory({ initialEntries: [path] }),
  })
  render(<RouterProvider router={router} />)
  return router
}

afterEach(() => vi.restoreAllMocks())

describe('the freelancer steps', () => {
  const base = FREELANCER_STEPS.reduce(
    (form, step) => ({ ...form, [step.id]: '' }),
    {} as Record<string, unknown>,
  )
  const step = (id: string) => FREELANCER_STEPS.find((s) => s.id === id)!

  it('accept an empty LinkedIn and refuse one that is not on linkedin.com', () => {
    const validate = step('linkedin_url').validate
    expect(validate({ ...base, linkedin_url: '' } as never)).toBeNull()
    expect(validate({ ...base, linkedin_url: 'https://www.linkedin.com/in/ada' } as never)).toBeNull()
    expect(validate({ ...base, linkedin_url: 'https://twitter.com/ada' } as never)).not.toBeNull()
  })

  it('read the Italian comma in the rate', () => {
    const validate = step('tariffa_giornaliera').validate
    expect(validate({ ...base, tariffa_giornaliera: '450,50' } as never)).toBeNull()
    expect(validate({ ...base, tariffa_giornaliera: 'tanto' } as never)).not.toBeNull()
  })

  it('want a PDF under five megabytes', () => {
    const validate = step('cv').validate
    const pdf = new File(['%PDF'], 'cv.pdf', { type: 'application/pdf' })
    const png = new File(['x'], 'cv.png', { type: 'image/png' })
    expect(validate({ ...base, cv: pdf } as never)).toBeNull()
    expect(validate({ ...base, cv: png } as never)).not.toBeNull()
    expect(validate({ ...base, cv: null } as never)).not.toBeNull()
  })
})

describe('readPerk', () => {
  it('reads the guide off the URL the landing\'s button carries, and nothing else', () => {
    expect(readPerk('?perk=guida')).toBe('guida')
    expect(readPerk('?utm_source=linkedin&perk=guida')).toBe('guida')
    expect(readPerk('?perk=crm')).toBeNull()
    expect(readPerk('')).toBeNull()
  })
})

describe('FreelancerWizard', () => {
  it('says why to finish when the URL says the person came for the guide (ORB-154)', async () => {
    mount('/freelance?perk=guida')
    const note = await screen.findByRole('note', { name: 'Perché completare l’iscrizione' })
    expect(note).toHaveTextContent('Completa l’iscrizione per scaricare la guida per diventare un freelance tech.')
    expect(note).toHaveTextContent('lo trovi nella tua area appena sei dentro')
    // The wizard itself is untouched: same heading, same first question.
    expect(screen.getByRole('heading', { level: 1, name: 'Entra in Orbiters' })).toBeInTheDocument()
  })

  it('shows no such note to whoever arrives without the key', async () => {
    mount()
    await screen.findByRole('heading', { level: 1, name: 'Entra in Orbiters' })
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('walks the eight questions, posts the multipart body with the UTM and lands on grazie', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 201 }),
    )
    const router = mount()

    await user.type(await screen.findByLabelText('Nome'), 'Ada')
    await user.type(screen.getByLabelText('Cognome'), 'Lovelace{Enter}')
    await user.type(screen.getByLabelText('Email'), 'ada@studio.it{Enter}')
    await user.keyboard('{Enter}') // LinkedIn, optional
    const cv = new File(['%PDF-1.7'], 'Ada CV.pdf', { type: 'application/pdf' })
    await user.upload(screen.getByLabelText('CV'), cv)
    await user.click(screen.getByRole('button', { name: /Avanti/ }))
    await user.type(screen.getByLabelText('Tariffa a giornata'), '450{Enter}')
    await user.type(screen.getByLabelText('Posizione'), 'Backend developer{Enter}')
    await user.click(screen.getByRole('radio', { name: /Da remoto/ }))
    await user.click(screen.getByRole('button', { name: /Rivedi|Avanti/ }))
    await user.type(screen.getByLabelText('Link aggiuntivi'), 'https://github.com/ada')
    await user.click(screen.getByRole('button', { name: /Rivedi/ }))

    expect(screen.getByRole('heading', { name: 'Tutto giusto?' })).toBeInTheDocument()
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument()
    expect(screen.getByText('Ada CV.pdf')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Invia/ }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/grazie'))
    expect(router.state.location.search).toEqual({ chi: 'freelance' })

    const [url, init] = fetchSpy.mock.calls[0]!
    expect(url).toBe('/api/hub/freelancers')
    const body = init?.body as FormData
    expect(body.get('email')).toBe('ada@studio.it')
    expect(body.get('remoto')).toBe('remoto')
    expect(body.get('utm_source')).toBe('linkedin')
    expect(body.get('origine')).toBe('pigrocrm')
    expect(body.getAll('links')).toEqual(['https://github.com/ada'])
  })
})
