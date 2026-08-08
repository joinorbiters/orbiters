import { describe, expect, it } from 'vitest'
import { buildPersonColumns, displayNative } from './columns'
import type { FieldDefinition } from '@/lib/schema'
import type { Person } from './queries'

/**
 * Reads a native column's cell value the same way `DataTable` does internally --
 * through the column's own `accessorFn` -- for every native column below, all of
 * which carry one. Mirrors `features/customers/queries.test.ts`'s identical
 * helper, added there only after a live bug (see task-6-report.md): a native
 * column cleared through the edit form holds `""`, not `null`, and a naive
 * `value ?? EMPTY` does not catch it.
 */
function cellValue(column: ReturnType<typeof buildPersonColumns>[number], person: Person) {
  if (!('accessorFn' in column) || typeof column.accessorFn !== 'function') {
    throw new Error(`column "${String(column.header)}" has no accessorFn to read`)
  }
  return column.accessorFn(person, 0)
}

const BASE_PERSON: Person = {
  id: 'p1',
  nome: 'Mario',
  cognome: null,
  email: null,
  telefono: null,
  ruolo: null,
  linkedin: null,
  note: null,
  customer_id: null,
  custom_fields: {},
  created_at: '2026-08-06T00:00:00Z',
  updated_at: '2026-08-06T00:00:00Z',
}

describe('buildPersonColumns', () => {
  it('shows the columns you need to call someone', () => {
    expect(buildPersonColumns([]).map((column) => column.header)).toEqual([
      'Nome',
      'Cognome',
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
    expect(buildPersonColumns([])).toHaveLength(5)
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
    const [, , , , , checkbox] = buildPersonColumns([disponibile])
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
    const [, , , , , score] = buildPersonColumns([punteggio])
    expect(cellValue(score!, { ...BASE_PERSON, custom_fields: { punteggio: 0 } })).toBe('0')
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
