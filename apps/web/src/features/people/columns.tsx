import { Link } from '@tanstack/react-router'
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
 * from this one), and this is the same four-line helper `features/customers/
 * columns.tsx` itself keeps local to its own file rather than lifting into a
 * shared module.
 */
export function displayNative(value: string | null): string {
  return value === null || value === '' ? EMPTY : value
}

/**
 * `Person` plus the one read field `lib/api-types.ts` does not carry yet.
 *
 * `PersonRead.customer_ragione_sociale` exists in
 * packages/core/src/pigrocrm/core/people/schemas.py as of this change, but the
 * generated types are produced by `npm run generate:api` against the API running
 * on :8000, which is not this code -- regenerating here would have written a file
 * from a *stale* server and deleted fields other features rely on. So the field is
 * declared here, next to its only consumer, and optionally: a `Person` decoded
 * from the current generated schema simply does not have it, which is exactly what
 * this type says. It is temporary -- once the controller regenerates
 * `api-types.ts`, `Person` carries the field itself and this alias collapses back
 * to `Person`.
 */

/**
 * TanStack Table v9 (pinned exactly in package.json): `ColumnDef` takes
 * `<TFeatures, TData, TValue>`, not v8's `<TData, TValue>` -- see
 * `features/customers/columns.tsx`'s identical comment for how this was
 * confirmed against `@tanstack/table-core`'s own types rather than assumed.
 * `DataTableFeatures` (`DataTable.tsx`'s own export) is the same `TFeatures`
 * every table in this product is instantiated with.
 *
 * Order -- Nome, Cognome, Azienda, Ruolo, Email, Telefono -- is "the columns you
 * need to call someone", not alphabetical or wire order: who they are, where they
 * work, what they do there, then how to reach them. «Azienda» sits immediately
 * after the surname because it is read as part of the identity ("Mario Rossi, ACME
 * Srl") rather than as contact detail, and it is a link to the customer, so the
 * person's company is one click away instead of a second search. Custom fields follow, one per active definition, so a
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
    {
      header: 'Azienda',
      id: 'customer_ragione_sociale',
      // The accessor stays a plain string -- the same `displayNative` dash every
      // other native column shows when there is nothing there (most people have no
      // customer at all: see `Person`'s own docstring in core). `cell` only *adds* a
      // link on top of that value, so the column still has one text value the table
      // can read, and «—» is never a link to nowhere.
      accessorFn: (row) => displayNative(row.customer_ragione_sociale ?? null),
      cell: ({ row }) => {
        const { customer_id, customer_ragione_sociale } = row.original
        const label = displayNative(customer_ragione_sociale ?? null)
        if (!customer_id || label === EMPTY) return label
        return (
          <Link
            to="/app/clienti/$customerId"
            params={{ customerId: customer_id }}
            className="underline underline-offset-2"
            // The whole row is already clickable (`DataTable`'s `onRowClick` sends it
            // to the person), so without this the company link fires two navigations
            // at once and the person wins -- clicking the company would open the
            // person, which is the one thing this cell must not do.
            onClick={(event) => event.stopPropagation()}
          >
            {customer_ragione_sociale}
          </Link>
        )
      },
    },
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
