import {
  Outlet,
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Thanks } from './Thanks'

function mount(chi: string) {
  const root = createRootRoute({ component: () => <Outlet /> })
  const grazie = createRoute({
    getParentRoute: () => root,
    path: '/grazie',
    validateSearch: (search: Record<string, unknown>): { chi: 'freelance' | 'azienda' } => ({
      chi: search.chi === 'azienda' ? 'azienda' : 'freelance',
    }),
    component: Thanks,
  })
  const router = createRouter({
    routeTree: root.addChildren([grazie]),
    history: createMemoryHistory({ initialEntries: [`/grazie?chi=${chi}`] }),
  })
  render(<RouterProvider router={router} />)
}

describe('the thank-you page', () => {
  it('tells a freelancer the area exists', async () => {
    mount('freelance')
    expect(await screen.findByRole('link', { name: /Entra nella tua area/ })).toHaveAttribute(
      'href',
      '/accedi',
    )
  })

  it('does not tell a company', async () => {
    mount('azienda')
    await screen.findByRole('heading', { name: 'Grazie, ci siamo.' })
    expect(screen.queryByRole('link', { name: /Entra nella tua area/ })).toBeNull()
  })
})
