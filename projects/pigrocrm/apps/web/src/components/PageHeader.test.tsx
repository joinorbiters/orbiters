/**
 * The page header every screen under the shell renders, now that the shell itself has no
 * top bar (spec §4: the search moved into the sidebar, the title into the white panel).
 *
 * Asserted through roles and text rather than through classes: what matters is that a
 * page has exactly one <h1>, that the primary action sits in the header rather than
 * somewhere in the page body, and that the optional slots are really optional.
 */
import { render, screen } from '@testing-library/react'
import { LayoutDashboard } from 'lucide-react'
import { describe, expect, it } from 'vitest'
import { PageHeader } from './PageHeader'

describe('PageHeader', () => {
  it('renders the title as the page heading', () => {
    render(<PageHeader icon={LayoutDashboard} title="Fatture" />)
    expect(screen.getByRole('heading', { level: 1, name: 'Fatture' })).toBeInTheDocument()
  })

  it('renders the description when there is one, and nothing when there is not', () => {
    const { unmount } = render(
      <PageHeader icon={LayoutDashboard} title="Fatture" description="Il registro del mese." />,
    )
    expect(screen.getByText('Il registro del mese.')).toBeInTheDocument()
    unmount()

    render(<PageHeader icon={LayoutDashboard} title="Fatture" />)
    expect(screen.queryByText('Il registro del mese.')).not.toBeInTheDocument()
  })

  it('renders the actions, which is where a page puts its primary button', () => {
    render(
      <PageHeader
        icon={LayoutDashboard}
        title="Fatture"
        actions={<button type="button">Crea fattura</button>}
      />,
    )
    expect(screen.getByRole('button', { name: 'Crea fattura' })).toBeInTheDocument()
  })

  it('renders the tabs row and the children slot', () => {
    render(
      <PageHeader
        icon={LayoutDashboard}
        title="Fatture"
        tabs={<a href="/app/fatture">Tutte</a>}
      >
        <p>filtri</p>
      </PageHeader>,
    )
    expect(screen.getByRole('link', { name: 'Tutte' })).toBeInTheDocument()
    expect(screen.getByText('filtri')).toBeInTheDocument()
  })

  it('hides the decorative icon from a screen reader, so the heading is read once', () => {
    const { container } = render(<PageHeader icon={LayoutDashboard} title="Fatture" />)
    // The icon repeats what the title already says; announcing it adds nothing.
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })
})
