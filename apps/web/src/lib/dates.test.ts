import { describe, expect, it } from 'vitest'
import { formatIsoDateItalian, startOfWeek, toIsoDate, toIsoMonth } from './dates'

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

describe('startOfWeek', () => {
  it('returns the Monday of the week the date falls in', () => {
    // Thursday 12 March 2026 -> Monday 9 March. Monday-first is a product decision
    // about what a working week looks like, not a locale lookup: an ICU default that
    // changed would otherwise silently reorder the columns of the hours grid.
    expect(toIsoDate(startOfWeek(new Date(2026, 2, 12)))).toBe('2026-03-09')
  })

  it('sends Sunday back six days, not zero', () => {
    // `getDay()` numbers Sunday 0, so the obvious `- getDay()` leaves Sunday on itself
    // and starts the week a day early for every other day of it. This is the assertion
    // that fails if that arithmetic is ever "simplified".
    expect(toIsoDate(startOfWeek(new Date(2026, 2, 15)))).toBe('2026-03-09')
  })

  it('leaves a Monday where it is', () => {
    expect(toIsoDate(startOfWeek(new Date(2026, 2, 9)))).toBe('2026-03-09')
  })

  it('crosses a month and a year boundary without shifting a day', () => {
    expect(toIsoDate(startOfWeek(new Date(2026, 0, 1)))).toBe('2025-12-29')
    expect(toIsoDate(startOfWeek(new Date(2027, 0, 3)))).toBe('2026-12-28')
  })

  it('drops the time of day, so a late-evening anchor names the same week as a morning one', () => {
    const late = startOfWeek(new Date(2026, 2, 12, 23, 30))
    expect([late.getHours(), late.getMinutes()]).toEqual([0, 0])
  })
})
