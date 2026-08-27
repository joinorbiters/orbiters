import { describe, expect, it } from 'vitest'
import { formatHoursValue, formatMoneyValue, formatRateValue } from './columns'

// `Intl.NumberFormat` separates an amount from its currency symbol with U+00A0, never
// an ordinary space -- a price must not wrap between its digits and its sign. Built
// from its code point rather than pasted, because `'2.500,50 €'` typed with a plain
// space compares unequal to what the formatter really returns, and that failure reads
// as a locale bug rather than as the invisible typo it is.
const NBSP = String.fromCharCode(0x00a0)

describe('the three formatters', () => {
  it('forces the thousands separator below five digits', () => {
    // it-IT's default grouping withholds the separator until the integer part has five
    // digits: `Intl.NumberFormat('it-IT').format(2500.5)` renders "2500,50". Every
    // currency surface in this product forces it on for that reason.
    expect(formatMoneyValue('2500.50')).toBe(`2.500,50${NBSP}€`)
    expect(formatHoursValue('1234.50')).toBe('1.234,5')
  })

  it('renders an absent value as a dash, never as zero', () => {
    // `null` is a real, distinct state: an unpriced hour is not a free hour.
    expect(formatMoneyValue(null)).toBe('—')
    expect(formatRateValue(null)).toBe('—')
    expect(formatMoneyValue('0.00')).toBe(`0,00${NBSP}€`)
  })

  it('shows a rate at the precision the column holds', () => {
    // Numeric(12,6): "33,333333 €/h" is not expressible at two places, which is the
    // whole reason the third scale exists. The unit is appended with an ordinary space:
    // "€/h" is a label this code writes itself, not part of what ICU formatted.
    expect(formatRateValue('33.333333')).toBe('33,333333 €/h')
  })
})
