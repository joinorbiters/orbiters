/**
 * The figures on the columns (ORB-139). Until now one segment per column carried a
 * value, the tallest, and only when it filled more than a third of the plot: most months
 * said nothing and the one figure shown read as the column's total when it was one
 * segment's. Now every segment tall enough to hold the text says its value, a column too
 * short for a label says it above, and a stacked column says its total above.
 */
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MonthlyBars } from './MonthlyBars'
import type { CashMonth } from './queries'

function month(
  mese: number,
  amounts: Partial<Record<'incassato' | 'da_incassare' | 'bozze' | 'costi', string>>,
  shares: Record<string, number>,
  totals: { andamento?: string; proiezione?: string } = {},
): CashMonth {
  return {
    anno: 2026,
    mese,
    incassato: amounts.incassato ?? '0.00',
    da_incassare: amounts.da_incassare ?? '0.00',
    bozze: amounts.bozze ?? '0.00',
    costi: amounts.costi ?? '0.00',
    totale_andamento: totals.andamento ?? amounts.incassato ?? '0.00',
    totale_proiezione: totals.proiezione ?? amounts.incassato ?? '0.00',
    quote_andamento: shares,
    quote_proiezione: shares,
  } as CashMonth
}

const ZERO = { incassato: 0, da_incassare: 0, bozze: 0, costi: 0 }
const EMPTY = Array.from({ length: 9 }, (_, i) => month(i + 4, {}, ZERO))

function column(mese: number) {
  return screen.getByTestId(`column-${mese}`)
}

describe('MonthlyBars', () => {
  it('labels every segment tall enough to hold its value, not only the tallest', () => {
    render(
      <MonthlyBars
        title="Proiezione"
        months={[
          month(
            1,
            { incassato: '4000.00', da_incassare: '3000.00', bozze: '2000.00' },
            { ...ZERO, incassato: 0.4, da_incassare: 0.3, bozze: 0.2 },
            { proiezione: '9000.00' },
          ),
          month(2, {}, ZERO),
          month(3, {}, ZERO),
        ]}
        series={['incassato', 'da_incassare', 'bozze', 'costi']}
        shares="quote_proiezione"
      />,
    )
    const gennaio = column(1)
    expect(within(gennaio).getByText('4.000,00 €')).toBeInTheDocument()
    expect(within(gennaio).getByText('3.000,00 €')).toBeInTheDocument()
    expect(within(gennaio).getByText('2.000,00 €')).toBeInTheDocument()
  })

  it('says the total above a stacked column, so the figure on top is the whole month', () => {
    render(
      <MonthlyBars
        title="Proiezione"
        months={[
          month(
            8,
            { incassato: '7813.91', da_incassare: '9970.12', bozze: '5000.00' },
            { ...ZERO, incassato: 0.3, da_incassare: 0.4, bozze: 0.2 },
            { proiezione: '22784.03' },
          ),
          ...EMPTY.slice(0, 2),
        ]}
        series={['incassato', 'da_incassare', 'bozze', 'costi']}
        shares="quote_proiezione"
      />,
    )
    const agosto = column(8)
    expect(within(agosto).getByTestId('column-total')).toHaveTextContent('22.784,03 €')
  })

  it('prints no total above a column with one segment: its value already says it', () => {
    render(
      <MonthlyBars
        title="Andamento"
        months={[month(6, { incassato: '7740.72' }, { ...ZERO, incassato: 1 }), ...EMPTY.slice(0, 2)]}
        series={['incassato', 'costi']}
        shares="quote_andamento"
      />,
    )
    const giugno = column(6)
    expect(within(giugno).getByText('7.740,72 €')).toBeInTheDocument()
    expect(within(giugno).queryByTestId('column-total')).toBeNull()
  })

  /** feb and apr in the screenshot that opened ORB-139: a column of a few pixels cannot
   *  hold a label, so its value goes above it rather than nowhere. */
  it('lifts the value above a column too short to hold it', () => {
    render(
      <MonthlyBars
        title="Andamento"
        months={[
          month(2, { incassato: '1000.00' }, { ...ZERO, incassato: 0.05 }),
          month(6, { incassato: '20000.00' }, { ...ZERO, incassato: 1 }),
          ...EMPTY.slice(0, 1),
        ]}
        series={['incassato', 'costi']}
        shares="quote_andamento"
      />,
    )
    const febbraio = column(2)
    expect(within(febbraio).getByTestId('column-total')).toHaveTextContent('1.000,00 €')
    // Inside the segment there is no room, so no second copy of the figure sits there.
    expect(within(febbraio).getByTestId('segment')).not.toHaveTextContent('1.000,00 €')
  })

  it('says nothing above an empty month', () => {
    render(
      <MonthlyBars
        title="Andamento"
        months={[month(6, { incassato: '20000.00' }, { ...ZERO, incassato: 1 }), ...EMPTY.slice(0, 2)]}
        series={['incassato', 'costi']}
        shares="quote_andamento"
      />,
    )
    expect(within(column(4)).queryByTestId('column-total')).toBeNull()
    expect(within(column(4)).queryByTestId('segment')).toBeNull()
  })
})
