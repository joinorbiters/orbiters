import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DateCell, EntityCell, MoneyCell } from './cells'

describe('DateCell', () => {
  it('renders an ISO date in Italian day/month/year order', () => {
    render(<DateCell value="2026-08-06" />)
    expect(screen.getByText('06/08/2026')).toBeInTheDocument()
  })

  it('puts a calendar icon before the date, hidden from assistive technology', () => {
    const { container } = render(<DateCell value="2026-08-06" />)
    const icon = container.querySelector('svg')
    expect(icon).not.toBeNull()
    expect(icon).toHaveAttribute('aria-hidden', 'true')
  })

  /**
   * Guards the timezone trap `lib/dates.ts` documents at length: parsing the ISO string
   * with the bare `Date` constructor reads it as UTC midnight, which formats a day early
   * anywhere behind UTC. This cell goes through `formatIsoDateItalian`, the one place
   * that knows it.
   */
  it('does not lose a day: the first of the month stays the first', () => {
    render(<DateCell value="2026-01-01" />)
    expect(screen.getByText('01/01/2026')).toBeInTheDocument()
  })

  it('renders an absent date as the same em dash every other empty cell shows, with no icon', () => {
    const { container } = render(<DateCell value={null} />)
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(container.querySelector('svg')).toBeNull()
  })

  it('treats an explicitly-cleared ("") date as absent too, never as a broken date', () => {
    const { container } = render(<DateCell value="" />)
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(container.querySelector('svg')).toBeNull()
  })
})

describe('MoneyCell', () => {
  /**
   * The figure is formatted by whichever feature owns it -- `features/invoices/format.ts`
   * parses the API's decimal string into integer cents, `features/time/columns.tsx` and
   * `features/deals/columns.tsx` have their own -- and reaches here already final. This
   * cell only aligns it, so no second money formatter (and no float) is introduced by
   * the shared table code.
   */
  it('shows the figure it is handed verbatim', () => {
    render(<MoneyCell>1.500,00 €</MoneyCell>)
    expect(screen.getByText('1.500,00 €')).toBeInTheDocument()
  })

  it('aligns the figure to the right, so a column of amounts lines up on the cent', () => {
    render(<MoneyCell>1.500,00 €</MoneyCell>)
    expect(screen.getByText('1.500,00 €').className).toContain('text-right')
  })
})

describe('EntityCell', () => {
  it('shows the name beside a chip of its initials', () => {
    render(<EntityCell name="ACME Srl" />)
    expect(screen.getByText('ACME Srl')).toBeInTheDocument()
    expect(screen.getByText('AS')).toBeInTheDocument()
  })

  it('takes at most two initials, from the first two words', () => {
    render(<EntityCell name="Acme Srl" />)
    expect(screen.getByText('CS')).toBeInTheDocument()
  })

  it('falls back to a single initial for a one-word name', () => {
    render(<EntityCell name="the previous system" />)
    expect(screen.getByText('M')).toBeInTheDocument()
  })

  /** The name is right there in words, so the chip is decoration and must not be read
   *  out as a second, meaningless "AS". */
  it('hides the initials chip from assistive technology', () => {
    const { container } = render(<EntityCell name="ACME Srl" />)
    const chip = container.querySelector('[data-slot="entity-initials"]')
    expect(chip).toHaveAttribute('aria-hidden', 'true')
  })

  it('adds a quiet second line when the caller has one', () => {
    render(<EntityCell name="Mario Rossi" sub="ACME Srl" />)
    expect(screen.getByText('Mario Rossi')).toBeInTheDocument()
    expect(screen.getByText('ACME Srl')).toBeInTheDocument()
  })

  it('shows no second line at all when there is nothing to put on it', () => {
    render(<EntityCell name="Mario Rossi" sub={null} />)
    expect(screen.queryByText('—')).not.toBeInTheDocument()
  })

  /** A record with no usable name still has to render a row: the em dash is the same
   *  absent value every other cell shows, and the chip goes away with it. */
  it('renders a nameless record as the empty dash rather than an empty chip', () => {
    const { container } = render(<EntityCell name="" />)
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(container.querySelector('[data-slot="entity-initials"]')).toBeNull()
  })
})
