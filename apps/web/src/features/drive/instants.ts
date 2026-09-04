/**
 * A *timestamp* formatter, not a fifth copy of `lib/dates.ts`. Those four helpers exist
 * for `date` columns -- bare `YYYY-MM-DD` strings, where `new Date(value)` parses as UTC
 * midnight and silently loses a day west of Greenwich. Everything Drive carries is an
 * instant with a zone in it (`2026-08-20T09:30:00Z`), so `new Date` is unambiguous and
 * that trap does not exist here. A copy of `features/gmail/instants.ts` rather than an
 * import from it: the two features are independent grants and neither should have to
 * change because the other one's formatter moved.
 */
const stamp = new Intl.DateTimeFormat('it-IT', { dateStyle: 'medium', timeStyle: 'short' })

/** `null` is "mai" and never a blank or an `Invalid Date`. */
export function formatInstant(value: string | null): string {
  if (!value) return 'mai'
  return stamp.format(new Date(value))
}
