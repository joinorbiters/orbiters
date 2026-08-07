import { tableFeatures, useTable, type ColumnDef, type RowData } from '@tanstack/react-table'
import type { KeyboardEvent } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'

// TanStack Table v9 (pinned exactly in package.json) is a from-scratch rewrite of
// v8, the API the original brief for this component was written against --
// `useReactTable`/`getCoreRowModel` do not exist in 9.0.0 at all (confirmed by
// reading node_modules/@tanstack/table-core's own .d.ts files, not assumed from an
// earlier major version's docs). A `useLegacyTable` v8-compatibility shim does
// exist, but it is explicitly `@deprecated` in its own type signature -- a bridge
// for migrating an *existing* v8 codebase, not a foundation to build brand-new,
// long-lived shared UI on. `tableFeatures({})` + `useTable` is the current,
// documented, non-deprecated way to ask for a plain table with none of v9's
// optional features (sorting, filtering, pagination, grouping, ...) switched on --
// exactly what every list this product has today needs, and the same shape
// TanStack's own "Quick Start" guide uses for this exact case.
const features = tableFeatures({})

/**
 * The `TFeatures` every `DataTable` column array is parameterised with: no
 * optional feature is registered, so `ColumnDef`'s feature-contributed options
 * (`enableSorting`, `filterFn`, ...) are not offered and cannot be set only to be
 * silently ignored. Exported so a caller can type its own `columns` array --
 * `ColumnDef<DataTableFeatures, Customer>[]` -- without reaching into
 * `@tanstack/react-table` for `tableFeatures` itself, or for `stockFeatures` (the
 * all-features-at-once shortcut the library's own v9 migration guide flags as a
 * bundle-size regression outside of migrating pre-existing v8 code) just to
 * satisfy this file's prop type.
 */
export type DataTableFeatures = typeof features

// `RowData` (table-core's own bound: `Record<string, any> | Array<any>`, see
// node_modules/.../@tanstack/table-core/dist/types/type-utils.d.ts) is what
// `ColumnDef`'s own `TData` parameter requires -- an unconstrained `<T>` here
// cannot be proven to satisfy it, since `T` could otherwise be instantiated with
// a primitive. Every real row this table renders (Customer, Person, Deal, ...) is
// already record-shaped, so this only makes an existing assumption explicit.
interface DataTableProps<T extends RowData> {
  columns: ColumnDef<DataTableFeatures, T>[]
  data: T[]
  isLoading?: boolean
  onRowClick?: (row: T) => void
  emptyMessage?: string
}

const LOADING_ROW_COUNT = 5

/**
 * One table for every list this product shows -- Clienti, Persone, Deal today,
 * whatever a later slice adds tomorrow.
 *
 * `isLoading` and "zero rows" render as deliberately different shapes, not the
 * same table with different text in one cell: a felt sense of "something is
 * happening" (animated skeleton bars, no header at all) versus a real, completed,
 * honestly-empty result (the full table chrome, one row stating so in words).
 * Collapsing the two into one state would let a slow network masquerade as
 * "there is nothing here", which is a different claim and not this component's
 * to make on the caller's behalf.
 */
export function DataTable<T extends RowData>({
  columns,
  data,
  isLoading,
  onRowClick,
  emptyMessage = 'Nessun risultato.',
}: DataTableProps<T>) {
  const table = useTable({ features, columns, data })

  if (isLoading) {
    return (
      <div className="space-y-2" role="status" aria-label="Caricamento">
        {Array.from({ length: LOADING_ROW_COUNT }, (_, index) => (
          <Skeleton key={index} className="h-12 w-full" />
        ))}
      </div>
    )
  }

  // Enter/Space activate a clickable row from the keyboard, mirroring what
  // `onClick` already gives the mouse: a bare `<tr onClick>` is only ever reachable
  // by a pointer, and every row below also gets `tabIndex={0}` so Tab reaches it in
  // the first place. This is the one shared table every future list in the product
  // renders through, so a gap here is not local to a single screen.
  function handleRowKeyDown(event: KeyboardEvent<HTMLTableRowElement>, row: T) {
    if (!onRowClick) return
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    onRowClick(row)
  }

  return (
    <div className="rounded-md border bg-card">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((group) => (
            <TableRow key={group.id}>
              {group.headers.map((header) => (
                <TableHead key={header.id}>
                  {header.isPlaceholder ? null : <table.FlexRender header={header} />}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={columns.length} className="h-24 text-center text-muted-foreground">
                {emptyMessage}
              </TableCell>
            </TableRow>
          ) : (
            table.getRowModel().rows.map((row) => (
              <TableRow
                key={row.id}
                onClick={() => onRowClick?.(row.original)}
                onKeyDown={(event) => handleRowKeyDown(event, row.original)}
                tabIndex={onRowClick ? 0 : undefined}
                className={cn(
                  onRowClick && 'cursor-pointer focus-visible:bg-muted/50 focus-visible:outline-none',
                )}
              >
                {row.getAllCells().map((cell) => (
                  <TableCell key={cell.id}>
                    <table.FlexRender cell={cell} />
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  )
}
