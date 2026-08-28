import { toIsoDate, toIsoMonth } from '@/lib/dates'

/** The window every report on `/analisi` is read over. `YYYY-MM-DD` on both ends, which
 *  is what `from`/`to` are declared as on the wire. */
export interface Period {
  from: string
  to: string
}

/**
 * The first day of a `YYYY-MM` month, and the last.
 *
 * Both built from local date parts through `lib/dates.ts`, never `toISOString()`: that
 * converts to UTC first, so east of Greenwich late in the evening the last day of March
 * comes back as the first of April and a month of invoices falls out of the report.
 *
 * `new Date(year, month, 0)` is day zero of the *following* month, which JavaScript
 * resolves to the last day of this one -- so February gets 28 or 29 without this module
 * knowing which, and without a table of month lengths to keep correct.
 */
export function firstDayOfMonth(isoMonth: string): string {
  const [year, month] = isoMonth.split('-').map(Number)
  if (year === undefined || month === undefined) return isoMonth
  if (!Number.isFinite(year) || !Number.isFinite(month)) return isoMonth
  return toIsoDate(new Date(year, month - 1, 1))
}

export function lastDayOfMonth(isoMonth: string): string {
  const [year, month] = isoMonth.split('-').map(Number)
  if (year === undefined || month === undefined) return isoMonth
  if (!Number.isFinite(year) || !Number.isFinite(month)) return isoMonth
  return toIsoDate(new Date(year, month, 0))
}

/** The current calendar month, both ends inclusive: the default window every report on
 *  `/analisi` opens on, because it is the one somebody is most often asking about. */
export function currentMonthPeriod(): Period {
  const month = toIsoMonth(new Date())
  return { from: firstDayOfMonth(month), to: lastDayOfMonth(month) }
}
