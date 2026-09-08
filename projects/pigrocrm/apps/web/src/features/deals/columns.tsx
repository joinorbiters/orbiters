import type { ColumnDef } from '@tanstack/react-table'
import { DateCell, EntityCell, MoneyCell } from '@/components/cells'
import type { DataTableFeatures } from '@/components/DataTable'
import { renderFieldValue } from '@/components/DynamicFieldRenderer'
import { formatIsoDateItalian } from '@/lib/dates'
import { MONEY_SCALE, scaledFromDecimalString } from '@/lib/decimal'
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
 * own `displayNative` (see either file's docstring for the live bug this guards).
 * Both spellings reach a cell: a cleared native *text* column holds `""`, and since
 * task 4B-1 a cleared numeric or date column holds `null` -- see
 * `clearedNativeValue` in lib/schema.ts. Kept local rather than imported, matching
 * those two files' own precedent of a small per-feature display helper rather than
 * a shared module.
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

export function formatDate(value: string | null): string {
  return value === null ? EMPTY : formatIsoDateItalian(value)
}

/**
 * The Kanban column total: every deal's `valore_previsto` in the stage, summed
 * in exact integer cents and divided back to euros exactly once, purely for
 * display -- never re-summed as a float. A `null` (unpriced) deal contributes
 * nothing, the same way `formatMoney` shows it as a dash rather than as zero.
 *
 * The cents conversion used to live here as a private `centsFromDecimalString`;
 * it is now `lib/decimal.ts`'s `scaledFromDecimalString`, unchanged in behaviour
 * (this file's own 300-deal assertion in `columns.test.ts` is what proves that)
 * but generalised over the scale, because slice 4's week grid and costs panel
 * need the identical arithmetic on hours and on rates. A second copy is how two
 * screens start disagreeing about the same euro; `lib/decimal.ts`'s docstring
 * carries the full reasoning for why money never touches a float here.
 */
export function sumValorePrevisto(deals: Deal[]): string {
  const totalCents = deals.reduce(
    (sum, deal) =>
      sum +
      (deal.valore_previsto === null
        ? 0
        : scaledFromDecimalString(deal.valore_previsto, MONEY_SCALE)),
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
    {
      header: 'Nome',
      accessorKey: 'nome',
      // The first cell carries the deal's identity as a chip (design spec §4). No
      // second line under it yet: the reference puts the customer there, and `DealRead`
      // (packages/core/.../deals/schemas.py) carries only `customer_id` -- no
      // `customer_ragione_sociale`, the way `PersonRead` does -- so the name is not in
      // this response at all. Reading it would mean one request per row; the field
      // belongs on `DealRead` first, and the sub-line follows for free the day it is
      // there.
      cell: ({ row }) => <EntityCell name={row.original.nome} />,
    },
    {
      header: 'Valore previsto',
      id: 'valore_previsto',
      accessorFn: (row) => formatMoney(row.valore_previsto),
      // `meta.align` right-aligns the header over the digits too; `MoneyCell` alone
      // could only align what is inside the cell.
      meta: { align: 'right' },
      cell: ({ row }) => <MoneyCell>{formatMoney(row.original.valore_previsto)}</MoneyCell>,
    },
    {
      header: 'Probabilità',
      id: 'probabilita',
      accessorFn: (row) => `${row.probabilita}%`,
      // A percentage is a number: it belongs on the right with the money, so a column
      // of them can be scanned down the units digit.
      meta: { align: 'right' },
    },
    {
      header: 'Chiusura prevista',
      id: 'data_chiusura_prevista',
      // `DateCell` formats the raw ISO value through the same `lib/dates.ts`
      // `formatDate` above calls, and adds the calendar icon.
      accessorFn: (row) => formatDate(row.data_chiusura_prevista),
      cell: ({ row }) => <DateCell value={row.original.data_chiusura_prevista} />,
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
