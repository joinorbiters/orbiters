import type { ColumnDef } from '@tanstack/react-table'
import type { DataTableFeatures } from '@/components/DataTable'
import { renderFieldValue } from '@/components/DynamicFieldRenderer'
import type { FieldDefinition } from '@/lib/schema'
import type { Customer } from './queries'

const EMPTY = '—'

/**
 * `null` and `""` both mean "nothing here" for a native text column -- unlike a
 * dynamic field (`renderFieldValue`'s job, in DynamicFieldRenderer.tsx), a native
 * column has no field type that could make `0`/`false` a legitimate value to
 * preserve, so the wider check is safe here and `??` alone is not: `CustomerForm`'s
 * own "clear a field" path (see that file's docstring on `submit`) sends an
 * explicit `""` -- never `null` -- to clear a native column, because the backend's
 * `CustomerUpdate.model_dump(exclude_none=True)` only drops an actual `None`, so
 * `null` would just be silently ignored instead of clearing anything. `??` alone
 * would then render that legitimately-cleared value as a blank cell instead of the
 * same dash every other absent value gets -- reproduced live while testing the
 * edit form, not a theoretical gap.
 */
export function displayNative(value: string | null): string {
  return value === null || value === '' ? EMPTY : value
}

/**
 * TanStack Table v9 (pinned exactly in package.json) is a from-scratch rewrite of
 * v8: `ColumnDef` takes `<TFeatures, TData, TValue>`, not v8's `<TData, TValue>` --
 * confirmed by reading `@tanstack/table-core`'s own `ColumnDef.d.ts`, not assumed
 * from an earlier major version's docs. `DataTableFeatures` (DataTable.tsx's own
 * export) is the `TFeatures` every table in this product is instantiated with, so
 * this is the same type parameter `DataTable`'s own `columns` prop already requires
 * -- getting it right here is what lets `<DataTable columns={buildCustomerColumns(...)} />`
 * type-check at all.
 *
 * Native columns first, then one per custom field -- so a field defined at runtime
 * through `POST /api/field-definitions` shows up in this table with no code change,
 * no rebuild, no deploy. `customFields` already excludes archived definitions (see
 * `useEntitySchema`/`describe_specs`), so there is nothing here to filter a second
 * time.
 */
export function buildCustomerColumns(
  customFields: FieldDefinition[],
): ColumnDef<DataTableFeatures, Customer>[] {
  const native: ColumnDef<DataTableFeatures, Customer>[] = [
    { header: 'Ragione sociale', accessorKey: 'ragione_sociale' },
    { header: 'P.IVA', id: 'partita_iva', accessorFn: (row) => displayNative(row.partita_iva) },
    { header: 'Comune', id: 'comune', accessorFn: (row) => displayNative(row.comune) },
    { header: 'Email', id: 'email', accessorFn: (row) => displayNative(row.email) },
    { header: 'Telefono', id: 'telefono', accessorFn: (row) => displayNative(row.telefono) },
  ]

  // Prefixed `custom_` id so a tenant-defined key can never collide with a native
  // column's own id (`partita_iva`, `comune`, ...) even in the one case that would
  // otherwise be ambiguous: nothing today stops a custom field from being *named*
  // the same as a native column (FieldDefinitionService.create only checks for a
  // collision against other field definitions, not against native columns).
  const custom: ColumnDef<DataTableFeatures, Customer>[] = customFields.map((field) => ({
    header: field.label,
    id: `custom_${field.key}`,
    // `renderFieldValue`, not `value ?? EMPTY`: a custom field can be numeric,
    // currency or checkbox, where `0`/`false` are real values, not absent ones --
    // `renderFieldValue` already draws that line correctly (see its own docstring),
    // so this column reuses it instead of re-deciding it here.
    accessorFn: (row) => renderFieldValue(field, row.custom_fields[field.key]),
  }))

  return [...native, ...custom]
}
