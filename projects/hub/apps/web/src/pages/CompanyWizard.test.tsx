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
import { CompanyWizard } from './CompanyWizard'

vi.mock('@orbiters/analytics/browser', () => ({
  capture: vi.fn(),
  identifyUser: vi.fn(),
  resetUser: vi.fn(),
}))
import { capture } from '@orbiters/analytics/browser'

/** The wizard mounted on its own little router, so `navigate` has somewhere to go. */
function mount(path = '/aziende') {
  const root = createRootRoute({ component: () => <Outlet /> })
  const aziende = createRoute({ getParentRoute: () => root, path: '/aziende', component: CompanyWizard })
  const grazie = createRoute({
    getParentRoute: () => root,
    path: '/grazie',
    validateSearch: (s: Record<string, unknown>) => ({ chi: String(s.chi ?? '') }),
    component: () => <h1>Grazie</h1>,
  })
  const router = createRouter({
    routeTree: root.addChildren([aziende, grazie]),
    history: createMemoryHistory({ initialEntries: [path] }),
  })
  render(<RouterProvider router={router} />)
  return router
}

function captured(event: string) {
  return vi
    .mocked(capture)
    .mock.calls.filter(([name]) => name === event)
    .map(([, properties]) => properties)
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.clearAllMocks()
})

describe('CompanyWizard', () => {
  it('walks the five questions, posts the request and reports the funnel as azienda (ORB-185)', async () => {
    const user = userEvent.setup()
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 201 }),
    )
    const router = mount()

    await user.type(await screen.findByLabelText('Azienda'), 'ACME Srl{Enter}')
    expect(captured('wizard_iniziato')).toEqual([{ tipo: 'azienda' }])
    await user.type(screen.getByLabelText('Referente'), 'Ada Lovelace')
    await user.type(screen.getByLabelText('Email'), 'ada@acme.it{Enter}')
    await user.type(screen.getByLabelText('Progetto'), 'Dobbiamo rifare il backend del portale clienti.')
    await user.click(screen.getByRole('button', { name: /Avanti/ }))
    await user.type(screen.getByLabelText('Da quando'), '2026-10-01')
    await user.type(screen.getByLabelText('Per quanto'), '3 mesi{Enter}')
    await user.type(screen.getByLabelText('Budget a giornata'), '500{Enter}')
    expect(screen.getByRole('heading', { name: 'Tutto giusto?' })).toBeInTheDocument()
    expect(captured('wizard_passo').map((p) => p?.passo)).toEqual([0, 1, 2, 3, 4, 5])
    expect(captured('wizard_passo')[0]).toEqual({ tipo: 'azienda', passo: 0, passi: 5 })
    expect(captured('wizard_completato')).toEqual([])

    await user.click(screen.getByRole('button', { name: /Invia/ }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/grazie'))
    expect(router.state.location.search).toEqual({ chi: 'azienda' })
    expect(captured('wizard_completato')).toEqual([{ tipo: 'azienda' }])

    const [url, init] = fetchSpy.mock.calls[0]!
    expect(url).toBe('/api/hub/companies')
    expect(JSON.parse(init?.body as string)).toMatchObject({ nome_azienda: 'ACME Srl', budget_giornaliero: '500' })
  })
})
