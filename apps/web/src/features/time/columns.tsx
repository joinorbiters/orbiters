import type { ColumnDef } from '@tanstack/react-table'
import type { DataTableFeatures } from '@/components/DataTable'
import { renderFieldValue } from '@/components/DynamicFieldRenderer'
import type { FieldDefinition } from '@/lib/schema'
import type { TimeEntry } from './queries'

const EMPTY = '—'

// `useGrouping: 'always'` on every formatter, never the ICU default: it-IT withholds
// the thousands separator until the integer part has five digits (checked directly on
// this stack's ICU: `Intl.NumberFormat('it-IT').format(2500.5)` renders "2500,50"). A
// four-figure total silently losing its separator on one screen is exactly the
// inconsistency this product forces grouping on to avoid -- `features/deals/columns.tsx`
// and `DynamicFieldRenderer`'s `renderFieldValue` already force it for the same reason.
const euro = new Intl.NumberFormat('it-IT', {
  style: 'currency',
  currency: 'EUR',
  useGrouping: 'always',
})
const hours = new Intl.NumberFormat('it-IT', { useGrouping: 'always' })
// Six places, because a rate is Numeric(12,6): "33,333333 €/h" is not expressible at
// two, which is the whole reason the third scale exists (§6.1).
const rate = new Intl.NumberFormat('it-IT', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 6,
  useGrouping: 'always',
})

/**
 * `null` is a real, distinct state -- an hour nobody has priced is not a free hour --
 * so it renders as a dash and never as `0,00 €`.
 *
 * `Number()` here is a *display* conversion of a value that has already stopped being
 * arithmetic: `lib/no-float-money.test.ts` bans the float only where a total could be
 * born from it, and every figure reaching these formatters was summed by the API. The
 * guard keys on API field names, so a parameter named `value` is deliberately outside
 * it -- what keeps that honest is that nothing in this module adds, subtracts or
 * compares; it only formats one already-final value at a time.
 */
export function formatMoneyValue(value: string | null): string {
  return value === null ? EMPTY : euro.format(Number(value))
}

export function formatHoursValue(value: string | null): string {
  return value === null ? EMPTY : hours.format(Number(value))
}

export function formatRateValue(value: string | null): string {
  return value === null ? EMPTY : `${rate.format(Number(value))} €/h`
}

/**
 * `value` is the ISO `YYYY-MM-DD` string a `Date` column always stores.
 * `new Date("2026-03-10")` parses as UTC midnight, and formatting that with
 * `Intl.DateTimeFormat` renders in the browser's zone -- anywhere behind UTC that is
 * still the previous evening, so the date silently loses a day. Building the `Date`
 * from its parts in local time keeps construction and formatting in one zone. It is the
 * same trap Acme fell into from the other direction, with `toISOString()` on write.
 *
 * Copied rather than imported, following the precedent `features/deals/columns.tsx`
 * already set for its own `formatIsoDateItalian`: `DynamicFieldRenderer`'s copy is
 * deliberately private to that module (its eslint `allowExportNames` lists only
 * `renderFieldValue`), and widening that override to share four lines would trade a
 * documented copy for a rule loosened across a whole file.
 */
export function formatIsoDate(value: string): string {
  const [year, month, day] = value.split('-').map(Number)
  // The backend's own contract guarantees all three parts, but `noUncheckedIndexedAccess`
  // cannot know that from a `.split` result -- and a genuinely malformed value is exactly
  // when showing the raw string beats rendering "NaN/NaN/NaN".
  if (year === undefined || month === undefined || day === undefined) return value
  return new Intl.DateTimeFormat('it-IT').format(new Date(year, month - 1, day))
}

const ORIGIN_LABELS: Record<string, string> = {
  manuale: 'manuale',
  deal: 'dal deal',
  utente: "dall'utente",
  assente: 'assente',
}

export function buildTimeEntryColumns(
  customFields: FieldDefinition[],
): ColumnDef<DataTableFeatures, TimeEntry>[] {
  const native: ColumnDef<DataTableFeatures, TimeEntry>[] = [
    { header: 'Data', id: 'data', accessorFn: (row) => formatIsoDate(row.data) },
    { header: 'Ore', id: 'ore', accessorFn: (row) => formatHoursValue(row.ore) },
    { header: 'Descrizione', accessorKey: 'descrizione' },
    {
      header: 'Tariffa',
      id: 'tariffa_applicata',
      // The origin next to the value, because "80 €/h" and "80 €/h, dal deal" answer
      // two different questions, and the second is the one somebody asks when the
      // number looks wrong.
      accessorFn: (row) =>
        row.tariffa_applicata === null
          ? EMPTY
          : `${formatRateValue(row.tariffa_applicata)} (${
              ORIGIN_LABELS[row.tariffa_origine] ?? row.tariffa_origine
            })`,
    },
    {
      header: 'Valore',
      id: 'valore_riga',
      // Straight from the API. This is the number the timesheet prints next to the
      // entry, so it must be the server's own figure and not a product computed here.
      // `?? null` because the field is optional on the wire, and an absent value means
      // the same thing an explicit `null` does: nobody has priced this hour.
      accessorFn: (row) => formatMoneyValue(row.valore_riga ?? null),
    },
    {
      header: 'Stato',
      id: 'stato',
      accessorFn: (row) =>
        row.invoice_line_id !== null
          ? 'Fatturata'
          : row.fatturabile
            ? 'Da fatturare'
            : 'Non fatturabile',
    },
  ]

  // Prefixed `custom_` so a tenant-defined key can never collide with a native column's
  // id. The backend guard added in Task 4A-2 now refuses the collision at the source
  // too, but the prefix stays: it is what keeps the table correct for definitions
  // created before that guard existed.
  const custom: ColumnDef<DataTableFeatures, TimeEntry>[] = customFields.map((field) => ({
    header: field.label,
    id: `custom_${field.key}`,
    accessorFn: (row) => renderFieldValue(field, row.custom_fields[field.key]),
  }))

  return [...native, ...custom]
}
