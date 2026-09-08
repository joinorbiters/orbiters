/**
 * Four shapes, no library, and every one of them with an equivalent table.
 *
 * A chart without a table is a figure a screen reader does not read (§13), so the table is
 * not a fallback -- it is the accessible rendering, and the visual mark is decoration on
 * top of it. That is why every assertion below is on table semantics rather than on SVG.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BarRows, BigNumber, Sparkline } from './charts'

describe('BigNumber', () => {
  it('renders the value exactly as given, never reformatted', () => {
    // The API sends "1234.56" already formatted for it-IT upstream; the component must not
    // parse it. Parsing is what criterion 14 forbids.
    render(<BigNumber label="Fatturato" value="1.234,56 €" hint="imponibile, emesso" />)
    expect(screen.getByText('1.234,56 €')).toBeInTheDocument()
    expect(screen.getByText('Fatturato')).toBeInTheDocument()
    expect(screen.getByText('imponibile, emesso')).toBeInTheDocument()
  })

  it('associates the label with the value for a screen reader', () => {
    render(<BigNumber label="Deal aperti" value="12" />)
    expect(screen.getByRole('group', { name: /deal aperti/i })).toBeInTheDocument()
  })
})

describe('BarRows', () => {
  const rows = [
    { label: 'Lead', value: '3.000,00 €', ratio: 1, tone: 1 },
    { label: 'Offerta', value: '500,00 €', ratio: 0.166, tone: 2 },
  ]

  it('renders a real table with a caption', () => {
    render(<BarRows caption="Pipeline per stato" rows={rows} />)
    expect(screen.getByRole('table', { name: 'Pipeline per stato' })).toBeInTheDocument()
    expect(screen.getAllByRole('row')).toHaveLength(3) // header + two
  })

  it('shows every label and value as text', () => {
    render(<BarRows caption="Pipeline per stato" rows={rows} />)
    expect(screen.getByText('Lead')).toBeInTheDocument()
    expect(screen.getByText('3.000,00 €')).toBeInTheDocument()
  })

  it('draws the bar with a CSS width and marks it decorative', () => {
    render(<BarRows caption="Pipeline per stato" rows={rows} />)
    const bars = screen.getAllByTestId('bar-fill')
    expect(bars[0]).toHaveStyle({ width: '100%' })
    // The bar duplicates the number next to it, so it is hidden from the accessibility
    // tree rather than announced twice.
    expect(bars[0]).toHaveAttribute('aria-hidden', 'true')
  })

  it('gives a smaller ratio a proportionally smaller bar', () => {
    // Without this the clamp tests below pass on a component that ignores `ratio` and
    // hard-codes 100%, which is the shape a "clamped to 100%" assertion cannot see.
    render(<BarRows caption="Pipeline per stato" rows={rows} />)
    const bars = screen.getAllByTestId('bar-fill')
    expect(bars[1]).toHaveStyle({ width: '16.60%' })
  })

  it('clamps a ratio outside 0..1 instead of overflowing the row', () => {
    render(<BarRows caption="c" rows={[{ label: 'x', value: '1', ratio: 4, tone: 1 }]} />)
    expect(screen.getByTestId('bar-fill')).toHaveStyle({ width: '100%' })
  })

  it('clamps a negative ratio to nothing rather than to a backwards bar', () => {
    render(<BarRows caption="c" rows={[{ label: 'x', value: '1', ratio: -2, tone: 1 }]} />)
    expect(screen.getByTestId('bar-fill')).toHaveStyle({ width: '0.00%' })
  })

  it('paints each row from its own chart token, wrapping past the fifth', () => {
    // The tone is what makes five bars five colours; a component that ignored it would
    // pass every other assertion in this file.
    render(
      <BarRows
        caption="c"
        rows={[
          { label: 'a', value: '1', ratio: 1, tone: 1 },
          { label: 'b', value: '1', ratio: 1, tone: 3 },
          { label: 'f', value: '1', ratio: 1, tone: 6 },
        ]}
      />,
    )
    const bars = screen.getAllByTestId('bar-fill')
    expect(bars[0]).toHaveStyle({ backgroundColor: 'var(--chart-1)' })
    expect(bars[1]).toHaveStyle({ backgroundColor: 'var(--chart-3)' })
    // Six rows in a five-colour palette is a wrap, not a sixth colour and not a crash.
    expect(bars[2]).toHaveStyle({ backgroundColor: 'var(--chart-1)' })
  })

  it('renders an empty state rather than an empty table', () => {
    render(<BarRows caption="Pipeline per stato" rows={[]} />)
    expect(screen.getByText(/nessun dato/i)).toBeInTheDocument()
  })
})

describe('Sparkline', () => {
  const points = [
    { label: 'lun', value: '8,00', ratio: 1 },
    { label: 'mar', value: '0,00', ratio: 0 },
    { label: 'mer', value: '4,00', ratio: 0.5 },
  ]

  it('renders an SVG marked decorative and a table that carries the data', () => {
    render(<Sparkline caption="Ore per giorno" points={points} />)
    expect(screen.getByTestId('sparkline-svg')).toHaveAttribute('aria-hidden', 'true')
    expect(screen.getByRole('table', { name: 'Ore per giorno' })).toBeInTheDocument()
    expect(screen.getByText('mar')).toBeInTheDocument()
    expect(screen.getByText('0,00')).toBeInTheDocument()
  })

  it('plots each ratio at its own height, spanning the full width', () => {
    // The path is the only place the ratios are used at all, so an assertion on the
    // rendered `d` is what separates a real plot from three points drawn on one line.
    render(<Sparkline caption="Ore per giorno" points={points} />)
    const path = screen.getByTestId('sparkline-svg').querySelector('path')
    // viewBox is 240x48: y=0 is ratio 1 and y=48 is ratio 0, so the middle point sits on
    // the baseline and the last one halfway up.
    expect(path).toHaveAttribute('d', 'M0.0,0.0 L120.0,48.0 L240.0,24.0')
  })

  it('handles a single point without dividing by zero', () => {
    render(<Sparkline caption="c" points={[{ label: 'lun', value: '8', ratio: 1 }]} />)
    const svg = screen.getByTestId('sparkline-svg')
    expect(svg).toBeInTheDocument()
    // `width / (points.length - 1)` is a division by zero here; NaN coordinates render as
    // an invisible line rather than as an error, so the guard needs its own assertion.
    expect(svg.querySelector('path')?.getAttribute('d')).not.toMatch(/NaN/)
  })

  it('renders an empty state rather than a path with no points', () => {
    render(<Sparkline caption="Ore per giorno" points={[]} />)
    expect(screen.getByText(/nessun dato/i)).toBeInTheDocument()
    expect(screen.queryByTestId('sparkline-svg')).not.toBeInTheDocument()
  })
})
