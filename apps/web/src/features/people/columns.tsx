import type { ColumnDef } from '@tanstack/react-table'
import type { DataTableFeatures } from '@/components/DataTable'
import { renderFieldValue } from '@/components/DynamicFieldRenderer'
import type { FieldDefinition } from '@/lib/schema'
import type { Person } from './queries'

const EMPTY = '—'

/**
 * `null` and `""` both mean "nothing here" for a native text column -- identical
 * reasoning to `displayNative` in `features/customers/columns.tsx`: a native
 * column has no field type that could make `0`/`false` a legitimate value to
 * preserve (that is `renderFieldValue`'s job, for a dynamic custom field), so the
 * wider check is safe here and `??` alone is not. `PersonUpdate.model_dump(
 * exclude_none=True)` only drops an actual `None`, so clearing a native field
 * through `PersonForm` sends an explicit `""`, never `null` -- see that file's
 * own `submit` for why -- and `??` alone would render that legitimately-cleared
 * value as a blank cell instead of the same dash every other absent value gets.
 * Defined locally rather than imported from `features/customers/columns`: the two
 * features are not coupled today (Customer's own file has no reciprocal import
 * from this one), and this is the same four-line helper Task 6 chose to keep
 * local to its own `columns.tsx` rather than lifting into a shared module.
 */
export function displayNative(value: string | null): string {
  return value === null || value === '' ? EMPTY : value
}

/**
 * TanStack Table v9 (pinned exactly in package.json): `ColumnDef` takes
 * `<TFeatures, TData, TValue>`, not v8's `<TData, TValue>` -- see
 * `features/customers/columns.tsx`'s identical comment for how this was
 * confirmed against `@tanstack/table-core`'s own types rather than assumed.
 * `DataTableFeatures` (`DataTable.tsx`'s own export) is the same `TFeatures`
 * every table in this product is instantiated with.
 *
 * Order -- Nome, Cognome, Ruolo, Email, Telefono -- is "the columns you need to
 * call someone", not alphabetical or wire order: who they are, what they do,
 * then how to reach them. Custom fields follow, one per active definition, so a
 * field defined at runtime through `POST /api/field-definitions` shows up with
 * no code change, no rebuild, no deploy; `customFields` already excludes
 * archived definitions (`useEntitySchema`/`describe_specs`), so there is
 * nothing here to filter a second time.
 */
export function buildPersonColumns(
  customFields: FieldDefinition[],
): ColumnDef<DataTableFeatures, Person>[] {
  const native: ColumnDef<DataTableFeatures, Person>[] = [
    { header: 'Nome', accessorKey: 'nome' },
    { header: 'Cognome', id: 'cognome', accessorFn: (row) => displayNative(row.cognome) },
    { header: 'Ruolo', id: 'ruolo', accessorFn: (row) => displayNative(row.ruolo) },
    { header: 'Email', id: 'email', accessorFn: (row) => displayNative(row.email) },
    { header: 'Telefono', id: 'telefono', accessorFn: (row) => displayNative(row.telefono) },
  ]

  // Prefixed `custom_` id so a tenant-defined key can never collide with a
  // native column's own id -- identical reasoning (and identical residual gap:
  // `FieldDefinitionService.create` does not itself guard against this) as
  // `features/customers/columns.tsx`.
  const custom: ColumnDef<DataTableFeatures, Person>[] = customFields.map((field) => ({
    header: field.label,
    id: `custom_${field.key}`,
    // `renderFieldValue`, not `value ?? EMPTY`: a custom field can be numeric,
    // currency or checkbox, where `0`/`false` are real values, not absent ones.
    accessorFn: (row) => renderFieldValue(field, row.custom_fields[field.key]),
  }))

  return [...native, ...custom]
}
