/**
 * The header slice 1 §10.1 promised. Three regions: breadcrumb, search, actions.
 *
 * `breadcrumbFor` is a pure function and is tested as one, because the alternative is
 * asserting on rendered crumbs through a router mock and then not being able to tell a
 * routing failure from a labelling one. It lives in its own module rather than beside
 * the component so that `AppHeader.tsx` stays a component-only module and needs no
 * `react-refresh/only-export-components` override.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AppHeader } from './AppHeader'
import { breadcrumbFor } from './breadcrumb'

// AppHeader reads the current location. Mocked here rather than mounted inside a real
// router: this file is about what the header renders, not about routing.
vi.mock('@tanstack/react-router', () => ({
  useRouterState: () => ({ location: { pathname: '/app/clienti' } }),
}))

describe('breadcrumbFor', () => {
  it('labels the dashboard root', () => {
    expect(breadcrumbFor('/app')).toEqual(['Dashboard'])
    expect(breadcrumbFor('/app/')).toEqual(['Dashboard'])
  })

  it('labels a known section', () => {
    expect(breadcrumbFor('/app/clienti')).toEqual(['Clienti'])
    expect(breadcrumbFor('/app/impostazioni/campi')).toEqual(['Impostazioni', 'Campi'])
  })

  it('renders a detail route without leaking the id into the crumb', () => {
    expect(breadcrumbFor('/app/clienti/0192f3b2-8c1a-7c3d-9f4e-1a2b3c4d5e6f')).toEqual([
      'Clienti',
      'Dettaglio',
    ])
  })

  it('falls back to a capitalised segment for an unmapped path', () => {
    expect(breadcrumbFor('/app/qualcosa')).toEqual(['Qualcosa'])
  })
})

describe('AppHeader', () => {
  it('shows a search control with the keyboard shortcut visible', () => {
    render(<AppHeader onOpenSearch={vi.fn()} />)
    const trigger = screen.getByRole('button', { name: /cerca/i })
    expect(trigger).toBeInTheDocument()
    // Spec §13: "campo di ricerca al centro con la scorciatoia visibile". Visible, not
    // discoverable by trying it.
    expect(trigger).toHaveTextContent(/K/)
  })

  it('calls onOpenSearch when the control is activated', async () => {
    const onOpenSearch = vi.fn()
    render(<AppHeader onOpenSearch={onOpenSearch} />)
    await userEvent.click(screen.getByRole('button', { name: /cerca/i }))
    expect(onOpenSearch).toHaveBeenCalledTimes(1)
  })

  it('is a landmark so a screen reader can skip to it', () => {
    render(<AppHeader onOpenSearch={vi.fn()} />)
    expect(screen.getByRole('banner')).toBeInTheDocument()
  })

  it('renders the crumbs for the current location, marking the last as the page', () => {
    // Without this the assertions above would still pass with `location` ignored
    // entirely and a hardcoded crumb list rendered.
    render(<AppHeader onOpenSearch={vi.fn()} />)
    expect(screen.getByRole('navigation', { name: 'Percorso' })).toHaveTextContent('Clienti')
    expect(screen.getByText('Clienti')).toHaveAttribute('aria-current', 'page')
  })
})
