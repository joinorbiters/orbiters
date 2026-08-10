import type { ColumnDef } from '@tanstack/react-table'
import type { DataTableFeatures } from '@/components/DataTable'
import { renderFieldValue } from '@/components/DynamicFieldRenderer'
import type { FieldDefinition } from '@/lib/schema'
import type { Deal } from './queries'

const EMPTY = '—'

// `useGrouping: 'always'` on every formatter below, not the ICU default: see
// DynamicFieldRenderer.tsx's own `renderFieldValue` docstring for the verified
// reason -- it-IT's default "auto"/"min2" grouping withholds the thousands
// separator until the integer part has five digits or more (checked directly on
// this stack's ICU: `Intl.NumberFormat('it-IT').format(2500.5)` renders "2500,50",
// no separator). Every currency/number surface in this product already forces
// grouping on for exactly that reason; a Deal-specific formatter that skipped it
// would be the one screen where a four-figure deal silently lost its separator,
// failing `KanbanBoard.test.tsx`'s own required assertion that a Kanban column's
// total renders with one ("shows the total value per column in euros, with a
// thousands separator", asserting `/2\.500,50/`).
const euro = new Intl.NumberFormat('it-IT', {
  style: 'currency',
  currency: 'EUR',
  useGrouping: 'always',
})
const number = new Intl.NumberFormat('it-IT', { useGrouping: 'always' })

/**
 * `null` and `""` both mean "nothing here" for a native text column -- identical
 * reasoning to `features/customers/columns.tsx`/`features/people/columns.tsx`'s
 * own `displayNative` (see either file's docstring for the live bug this guards:
 * a cleared native column holds `""`, never `null` -- `DealUpdate.model_dump(
 * exclude_none=True)` only drops an actual `None`). Kept local rather than
 * imported, matching those two files' own precedent of a small per-feature
 * display helper rather than a shared module.
 */
export function displayNative(value: string | null): string {
  return value === null || value === '' ? EMPTY : value
}

/**
 * A Deal-specific currency formatter, not `renderFieldValue`: `valore_previsto`/
 * `valore_preventivato` are native `Decimal` columns (deals/models.py), not a
 * tenant-defined custom field, so there is no `FieldDefinition` to hand
 * `renderFieldValue`. `null` is a real, absent state (a deal nobody has priced
 * yet yields `None`); an empty string cannot occur here the way it can for a
 * native text column -- `DealUpdate` has no supported way to write `""` into a
 * `Decimal` field at all (see `sumValorePrevisto`'s docstring below for the one
 * place this matters on this screen).
 */
export function formatMoney(value: string | null): string {
  return value === null ? EMPTY : euro.format(Number(value))
}

/** Same reasoning as `formatMoney`, for the one native column that is a plain
 *  quantity rather than money: `ore_preventivate` (`Numeric(8, 2)`, deals/
 *  models.py). Kept distinct from `formatMoney` rather than reusing it with a
 *  flag: a value here is never a euro amount, and `renderFieldValue`'s own
 *  `'number'` case (DynamicFieldRenderer.tsx) uses the identical formatter for
 *  the identical reason on a custom numeric field. */
export function formatHours(value: string | null): string {
  return value === null ? EMPTY : number.format(Number(value))
}

/**
 * `value` is the ISO "YYYY-MM-DD" string `data_chiusura_prevista` always stores
 * (a `Date` column, deals/models.py) -- the same shape, and the same timezone
 * trap, as a custom `date` field. Duplicated from DynamicFieldRenderer.tsx's
 * `formatIsoDateItalian` rather than imported: that function is deliberately
 * private to that module (only `renderFieldValue` is in its own eslint
 * `allowExportNames`), and `displayNative` above is already this project's
 * precedent for a tiny per-feature display helper living next to its one caller
 * instead of in a shared module.
 *
 * `new Date("2026-08-06")` parses as UTC midnight; formatting it with
 * `Intl.DateTimeFormat` then renders in whichever zone the browser is in --
 * anywhere *behind* UTC, that is still the *previous* evening, so the formatted
 * date silently loses a day. Building the `Date` from its year/month/day parts in
 * local time keeps construction and formatting in the same zone.
 */
function formatIsoDateItalian(value: string): string {
  const [year, month, day] = value.split('-').map(Number)
  if (year === undefined || month === undefined || day === undefined) return value
  return new Intl.DateTimeFormat('it-IT').format(new Date(year, month - 1, day))
}

export function formatDate(value: string | null): string {
  return value === null ? EMPTY : formatIsoDateItalian(value)
}

/**
 * Exact money arithmetic for the one place on this screen that adds several
 * deals' values together: a Kanban column's total (`sumValorePrevisto` below).
 * `Deal.valore_previsto` is `Numeric(12, 2)` in Postgres specifically so money is
 * never a binary float (deals/models.py's own comment: "a binary float cannot
 * represent 1234.56 exactly, and that drift is a bug the moment it reaches an
 * invoice"). `deals.reduce((sum, deal) => sum + Number(deal.valore_previsto ??
 * 0), 0)` throws that guarantee away the moment two or more deals are summed on
 * the client, by routing the addition back through the exact representation
 * `Numeric` exists to avoid.
 *
 * The fix is to never let a fractional value touch a floating-point operation at
 * all: split the decimal string into its integer and fractional parts as
 * *strings*, parse each half separately, and combine with integer arithmetic.
 * This is not pedantry -- checked directly in this project's own Node runtime,
 * `Number("0.29") * 100` equals `28.999999999999996`, not `29`. Multiplying a
 * parsed fractional float by 100 to get cents reintroduces the exact drift this
 * function exists to avoid, so the fractional digits are read off the string
 * instead of ever being multiplied; only the whole-number part (already an
 * integer) is multiplied by 100, which is always exact.
 *
 * Every value `Numeric(12, 2)` can hold is at most 10 integer digits, so its
 * cents representation is at most 12 digits -- far under `Number.
 * MAX_SAFE_INTEGER`'s 16, even summed across thousands of rows. Plain `number`
 * integer arithmetic is therefore exact here; nothing about this needs `BigInt`,
 * only the discipline of never multiplying or dividing a fractional value.
 *
 * Empirically, a *small* realistic portfolio (a handful of ordinary deal
 * amounts) essentially never shows a *visibly* wrong two-decimal total under the
 * naive float approach either -- the per-term error is far below the rounding
 * threshold. It takes several hundred deals priced near the top of `Numeric(12,
 * 2)`'s range summed together to push the naive total's *displayed* cents off by
 * one (verified directly: 300 deals priced from 9999999999.99 down by 1000003
 * each cent sum to exactly 2955149865447.00 -- cross-checked independently with
 * Python's `Decimal` -- while summing the same 300 values as plain floats
 * displays 2955149865447.02, two cents high; see `columns.test.ts`). That does
 * not make the naive version merely a theoretical nit: it fails exactly the way
 * `Numeric` over `Float` fails on the backend, silently and only once the numbers
 * get big enough for anyone to actually notice.
 */
function centsFromDecimalString(value: string): number {
  const negative = value.startsWith('-')
  const unsigned = negative ? value.slice(1) : value
  const [wholePart, fractionPart = ''] = unsigned.split('.')
  const cents = Number(wholePart || '0') * 100 + Number((fractionPart + '00').slice(0, 2))
  return negative ? -cents : cents
}

/** The Kanban column total: every deal's `valore_previsto` in the stage, summed
 *  in exact integer cents (see `centsFromDecimalString`) and divided back to
 *  euros exactly once, purely for display -- never re-summed as a float. A
 *  `null` (unpriced) deal contributes nothing, the same way `formatMoney` shows
 *  it as a dash rather than as zero. */
export function sumValorePrevisto(deals: Deal[]): string {
  const totalCents = deals.reduce(
    (sum, deal) =>
      sum + (deal.valore_previsto === null ? 0 : centsFromDecimalString(deal.valore_previsto)),
    0,
  )
  return euro.format(totalCents / 100)
}

/**
 * TanStack Table v9 (pinned exactly in package.json): `ColumnDef` takes
 * `<TFeatures, TData, TValue>`, not v8's `<TData, TValue>` -- see `features/
 * customers/columns.tsx`'s identical comment for how this was confirmed against
 * `@tanstack/table-core`'s own types. `DataTableFeatures` (`DataTable.tsx`'s own
 * export) is the same `TFeatures` every table in this product is instantiated
 * with.
 *
 * Native columns first, then one per custom field, matching Customer/Person's
 * own convention: a field defined at runtime through `POST /api/field-
 * definitions` shows up here with no code change. `customFields` already
 * excludes archived definitions (`useEntitySchema`/`describe_specs`), so there is
 * nothing here to filter a second time. `ore_preventivate`/`valore_preventivato`
 * are deliberately not table columns, matching the detail route's own
 * "Preventivo" card (`routes/app/deal/$dealId.tsx`): they are written now but
 * not read until the slice 4 estimate-vs-actual report.
 */
export function buildDealColumns(customFields: FieldDefinition[]): ColumnDef<DataTableFeatures, Deal>[] {
  const native: ColumnDef<DataTableFeatures, Deal>[] = [
    { header: 'Nome', accessorKey: 'nome' },
    {
      header: 'Valore previsto',
      id: 'valore_previsto',
      accessorFn: (row) => formatMoney(row.valore_previsto),
    },
    { header: 'Probabilità', id: 'probabilita', accessorFn: (row) => `${row.probabilita}%` },
    {
      header: 'Chiusura prevista',
      id: 'data_chiusura_prevista',
      accessorFn: (row) => formatDate(row.data_chiusura_prevista),
    },
  ]

  // Prefixed `custom_` id so a tenant-defined key can never collide with a
  // native column's own id -- identical reasoning (and identical residual gap:
  // `FieldDefinitionService.create` does not itself guard against this) as
  // `features/customers/columns.tsx`/`features/people/columns.tsx`.
  const custom: ColumnDef<DataTableFeatures, Deal>[] = customFields.map((field) => ({
    header: field.label,
    id: `custom_${field.key}`,
    accessorFn: (row) => renderFieldValue(field, row.custom_fields[field.key]),
  }))

  return [...native, ...custom]
}
