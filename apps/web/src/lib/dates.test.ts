import { describe, expect, it } from 'vitest'
import { formatIsoDateItalian, toIsoDate, toIsoMonth } from './dates'

describe('formatIsoDateItalian', () => {
  it('renders an ISO date in Italian order', () => {
    expect(formatIsoDateItalian('2026-08-06')).toBe('06/08/2026')
  })

  /**
   * The whole reason this function does not simply pass the string to `new Date`.
   * Constructed from local parts, the calendar day is the same number that was stored
   * whatever zone the browser is in -- the assertion that fails the moment somebody
   * "simplifies" the body back to `new Date(value)`.
   */
  it('keeps the calendar day when the local zone is behind UTC', () => {
    const parsedAsUtc = new Intl.DateTimeFormat('it-IT', { timeZone: 'America/New_York' }).format(
      new Date('2026-08-06'),
    )
    expect(parsedAsUtc).toBe('05/08/2026') // what the naive route would have shown
    expect(formatIsoDateItalian('2026-08-06')).toBe('06/08/2026')
  })

  it('shows a malformed value as it was stored rather than as NaN', () => {
    expect(formatIsoDateItalian('non-una-data')).toBe('non-una-data')
    expect(formatIsoDateItalian('')).toBe('')
  })
})

describe('toIsoDate', () => {
  it('reads the local parts, never the UTC ones', () => {
    // 1 March 2026, 00:30 local. `toISOString()` on this instant is still February in
    // any zone east of Greenwich -- the write-side half of the same bug.
    const localMidnightish = new Date(2026, 2, 1, 0, 30)
    expect(toIsoDate(localMidnightish)).toBe('2026-03-01')
  })

  it('pads month and day to two digits', () => {
    expect(toIsoDate(new Date(2026, 0, 5))).toBe('2026-01-05')
  })
})

describe('toIsoMonth', () => {
  it('drops the day and keeps the local month', () => {
    expect(toIsoMonth(new Date(2026, 11, 31, 23, 45))).toBe('2026-12')
  })
})
