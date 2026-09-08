/**
 * A *timestamp* formatter, not a fifth copy of `lib/dates.ts`. Those four helpers exist
 * for `date` columns -- bare `YYYY-MM-DD` strings, where `new Date(value)` parses as UTC
 * midnight and silently loses a day west of Greenwich. Everything Gmail carries is an
 * instant with a zone in it (`2026-08-20T09:30:00Z`), so `new Date` is unambiguous and
 * that trap does not exist here. Same shape as `PeriodsPanel`/`TokensPanel`/`Timeline`,
 * which all format instants this way.
 *
 * A module of its own rather than a helper inside `GmailPanel.tsx`, because the Email
 * tab needs the identical rendering and a component module that also exported this
 * would trip `react-refresh/only-export-components`. One formatter for the feature is
 * also one place for the locale to be wrong in, instead of two that drift.
 */
const stamp = new Intl.DateTimeFormat('it-IT', { dateStyle: 'medium', timeStyle: 'short' })

/** `null` is "mai" and never a blank or an `Invalid Date`: an account that has never
 *  synced has a real answer, and it is not an empty cell. */
export function formatInstant(value: string | null): string {
  if (!value) return 'mai'
  return stamp.format(new Date(value))
}
