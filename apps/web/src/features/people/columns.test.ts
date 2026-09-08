import { isValidElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { buildPersonColumns, displayNative } from './columns'
import type { FieldDefinition } from '@/lib/schema'
import type { Person } from './queries'

/** `buildPersonColumns` reads one field `api-types.ts` does not carry yet (see
 *  `columns.tsx`'s own `PersonRow`), so the fixtures here declare it too. */
type PersonRow = Person & { customer_ragione_sociale?: string | null }

/**
 * Reads a native column's cell value the same way `DataTable` does internally --
 * through the column's own `accessorFn` -- for every native column below, all of
 * which carry one. Mirrors `features/customers/queries.test.ts`'s identical
 * helper, added there only after a live bug (see task-6-report.md): a native
 * column cleared through the edit form holds `""`, not `null`, and a naive
 * `value ?? EMPTY` does not catch it.
 */
function cellValue(column: ReturnType<typeof buildPersonColumns>[number], person: PersonRow) {
  if (!('accessorFn' in column) || typeof column.accessorFn !== 'function') {
    throw new Error(`column "${String(column.header)}" has no accessorFn to read`)
  }
  return column.accessorFn(person, 0)
}

const BASE_PERSON: PersonRow = {
  id: 'p1',
  nome: 'Mario',
  cognome: null,
  email: null,
  telefono: null,
  ruolo: null,
  linkedin: null,
  note: null,
  customer_id: null,
  customer_ragione_sociale: null,
  custom_fields: {},
  created_at: '2026-08-06T00:00:00Z',
  updated_at: '2026-08-06T00:00:00Z',
}

describe('buildPersonColumns', () => {
  it('shows the columns you need to call someone', () => {
    expect(buildPersonColumns([]).map((column) => column.header)).toEqual([
      'Nome',
      'Cognome',
      'Azienda',
      'Ruolo',
      'Email',
      'Telefono',
    ])
  })

  it('appends custom field columns', () => {
    const headers = buildPersonColumns([
      { key: 'seniority', label: 'Seniority', type: 'text', required: false, options: [] },
    ]).map((column) => column.header)
    expect(headers).toContain('Seniority')
  })

  it('does not add columns for archived fields, which are simply not returned', () => {
    expect(buildPersonColumns([])).toHaveLength(6)
  })

  it('renders a null native field as the empty dash', () => {
    const [, cognome] = buildPersonColumns([])
    expect(cellValue(cognome!, { ...BASE_PERSON, cognome: null })).toBe('—')
  })

  it('renders an explicitly-cleared ("") native field as the same dash, never a blank cell', () => {
    const [, cognome] = buildPersonColumns([])
    expect(cellValue(cognome!, { ...BASE_PERSON, cognome: '' })).toBe('—')
  })

  it('renders a present native field as itself', () => {
    const [, cognome] = buildPersonColumns([])
    expect(cellValue(cognome!, { ...BASE_PERSON, cognome: 'Rossi' })).toBe('Rossi')
  })

  /** The table is one of the two read surfaces the "absent checkbox reads No" rule
   *  has to hold on (the detail page is the other, and goes through the same
   *  `renderFieldValue`). A record created before the field existed, or through
   *  the API, legitimately has no key at all -- and a dash there claims a third
   *  state a checkbox does not have. */
  it('renders a checkbox column as No when the record carries no value for it', () => {
    const disponibile: FieldDefinition = {
      key: 'disponibile',
      label: 'Disponibile per nuovi progetti',
      type: 'checkbox',
      required: false,
      options: [],
    }
    const [, , , , , , checkbox] = buildPersonColumns([disponibile])
    expect(cellValue(checkbox!, { ...BASE_PERSON, custom_fields: {} })).toBe('No')
    expect(cellValue(checkbox!, { ...BASE_PERSON, custom_fields: { disponibile: false } })).toBe('No')
    expect(cellValue(checkbox!, { ...BASE_PERSON, custom_fields: { disponibile: true } })).toBe('Sì')
  })

  it('keeps zero and false as real custom-field values, not a dash', () => {
    const punteggio: FieldDefinition = {
      key: 'punteggio',
      label: 'Punteggio',
      type: 'number',
      required: false,
      options: [],
    }
    const [, , , , , , score] = buildPersonColumns([punteggio])
    expect(cellValue(score!, { ...BASE_PERSON, custom_fields: { punteggio: 0 } })).toBe('0')
  })
})

/**
 * Reads a column's rendered cell the way `DataTable` does -- through `cell`, with the
 * row context TanStack hands it -- rather than only its `accessorFn`. The «Azienda»
 * column is the first on this table whose displayed value is not just its accessor
 * string: the accessor keeps a plain text value (so the dash still works, and so the
 * column has something a future sort or export could read), while `cell` turns a real
 * company into a link to that customer. Only `row.original` is consulted by the cell
 * under test, so the cast supplies exactly that and nothing else -- building a whole
 * `CellContext` would assert nothing more.
 */
function renderedCell(
  column: ReturnType<typeof buildPersonColumns>[number],
  person: PersonRow,
) {
  if (typeof column.cell !== 'function') {
    throw new Error(`column "${String(column.header)}" has no cell renderer`)
  }
  return column.cell({ row: { original: person } } as never)
}

describe("the person's company", () => {
  const WITH_COMPANY: PersonRow = {
    ...BASE_PERSON,
    customer_id: 'c1',
    customer_ragione_sociale: 'ACME Srl',
  }

  it('reads the company name straight from the row, with no second request', () => {
    const [, , azienda] = buildPersonColumns([])
    expect(cellValue(azienda!, WITH_COMPANY)).toBe('ACME Srl')
  })

  it('links the company to its customer page', () => {
    const [, , azienda] = buildPersonColumns([])
    const rendered = renderedCell(azienda!, WITH_COMPANY)
    expect(isValidElement(rendered)).toBe(true)
    const props = (rendered as { props: Record<string, unknown> }).props
    expect(props.to).toBe('/app/clienti/$customerId')
    expect(props.params).toEqual({ customerId: 'c1' })
    expect(props.children).toBe('ACME Srl')
  })

  /** The row itself is clickable (`DataTable`'s `onRowClick` opens the person), so a
   *  link that lets the click through would navigate twice and land on the person --
   *  the one place this cell must never go. */
  it('keeps the row click from firing alongside the link', () => {
    const [, , azienda] = buildPersonColumns([])
    const props = (renderedCell(azienda!, WITH_COMPANY) as { props: Record<string, unknown> })
      .props
    const stopPropagation = vi.fn()
    ;(props.onClick as (event: { stopPropagation: () => void }) => void)({ stopPropagation })
    expect(stopPropagation).toHaveBeenCalledOnce()
  })

  it('shows the empty dash, and no link, for a person with no company', () => {
    const [, , azienda] = buildPersonColumns([])
    expect(cellValue(azienda!, BASE_PERSON)).toBe('—')
    expect(renderedCell(azienda!, BASE_PERSON)).toBe('—')
  })

  /** A person whose `customer_id` is set but whose name did not arrive (an older
   *  API build, or a cached response from before this field existed) reads as the
   *  same dash rather than as an empty link with no text to click. */
  it('shows the dash when the id is there but the name is not', () => {
    const [, , azienda] = buildPersonColumns([])
    const nameless: PersonRow = { ...BASE_PERSON, customer_id: 'c1' }
    expect(renderedCell(azienda!, nameless)).toBe('—')
  })
})

describe('displayNative', () => {
  it('treats null and empty string as the same absent value', () => {
    expect(displayNative(null)).toBe('—')
    expect(displayNative('')).toBe('—')
  })

  it('renders a present value as itself', () => {
    expect(displayNative('Rossi')).toBe('Rossi')
  })
})
