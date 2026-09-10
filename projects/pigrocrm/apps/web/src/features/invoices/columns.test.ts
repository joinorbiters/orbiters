import { render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { describe, expect, it } from 'vitest'
import { buildInvoiceColumns, type InvoiceColumnOptions } from './columns'
import type { Invoice } from './queries'

const ISSUED = {
  anno: 2026,
  numero: 7,
  riferimento: null,
  tipo: 'fattura',
  stato: 'emessa',
  stato_pagamento: 'da_incassare',
  data_emissione: '2026-08-20',
  totale: '1500.00',
} as unknown as Invoice

const PROFORMA = {
  anno: null,
  numero: null,
  riferimento: 'PROV-2026-0007',
  tipo: 'proforma',
  stato: 'confermata',
  stato_pagamento: 'da_incassare',
  data_emissione: null,
  totale: '500.00',
} as unknown as Invoice

const WITH_CUSTOMER = { ...ISSUED, customer_ragione_sociale: 'ACME S.r.l.' } as Invoice

function accessor(id: string, row: Invoice, options?: InvoiceColumnOptions): unknown {
  const column = buildInvoiceColumns(options).find((candidate) => candidate.id === id)
  if (column === undefined || !('accessorFn' in column) || column.accessorFn === undefined) {
    throw new Error(`nessuna colonna con id ${id}`)
  }
  return column.accessorFn(row, 0)
}

describe('buildInvoiceColumns', () => {
  it('shows the fiscal number for an invoice and the reference for a proforma', () => {
    expect(accessor('numero', ISSUED)).toBe('2026/7')
    expect(accessor('numero', PROFORMA)).toBe('PROV-2026-0007')
  })

  it('formats the total as grouped euros', () => {
    expect(String(accessor('totale', ISSUED))).toContain('1.500,00')
  })

  it('shows an em dash where a proforma has no issue date', () => {
    expect(accessor('data_emissione', PROFORMA)).toBe('—')
  })

  it('does not offer a payment column value for a proforma', () => {
    // A proforma is never collected: showing "Da incassare" next to something nobody
    // owes is the kind of small lie a fiscal list should not tell.
    expect(accessor('stato_pagamento', PROFORMA)).toBe('—')
    expect(accessor('stato_pagamento', ISSUED)).toBe('Da incassare')
  })
})

/**
 * Reads a column's *rendered* cell, not only its accessor.
 *
 * Both halves of every column below still matter: the accessor keeps the plain text
 * value (asserted above, and what a future sort or export would read), while `cell`
 * carries the presentation the design revision asks for -- a calendar icon before a
 * date, a right-aligned figure, a state as a dotted pill (design spec §4). Only
 * `row.original` is consulted by these cells, so the cast supplies exactly that.
 */
function renderCell(id: string, row: Invoice, options?: InvoiceColumnOptions) {
  const column = buildInvoiceColumns(options).find((candidate) => candidate.id === id)
  if (column === undefined || typeof column.cell !== 'function') {
    throw new Error(`la colonna ${id} non ha un cell renderer`)
  }
  return render(column.cell({ row: { original: row } } as never) as ReactElement)
}

function column(id: string, options?: InvoiceColumnOptions) {
  const found = buildInvoiceColumns(options).find((candidate) => candidate.id === id)
  if (found === undefined) throw new Error(`nessuna colonna con id ${id}`)
  return found
}

describe('how an invoice row reads', () => {
  it('puts a calendar icon before the issue date', () => {
    const { container } = renderCell('data_emissione', ISSUED)
    expect(screen.getByText('20/08/2026')).toBeInTheDocument()
    expect(container.querySelector('svg')).not.toBeNull()
  })

  it('shows no date and no calendar icon for a proforma that has not been issued', () => {
    const { container } = renderCell('data_emissione', PROFORMA)
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(container.querySelector('svg')).toBeNull()
  })

  /** The header has to sit over the digits it labels, which only the column can say --
   *  a cell that right-aligned itself would leave its own header on the left. */
  it('declares the total a right-aligned column, not merely a right-aligned cell', () => {
    expect(column('totale').meta).toEqual({ align: 'right' })
  })

  it('right-aligns the total inside its cell too', () => {
    renderCell('totale', ISSUED)
    expect(screen.getByText(/1\.500,00/).className).toContain('text-right')
  })

  it('shows the fiscal state as a pill, tinted by what the state means', () => {
    renderCell('stato', ISSUED)
    const pill = screen.getByText('Emessa').closest('[data-slot="badge"]')
    expect(pill).toHaveAttribute('data-tone', 'ink')
  })

  it('shows an annulled invoice as a warning, because it keeps its number and stays in the register', () => {
    renderCell('stato', { ...ISSUED, stato: 'annullata' })
    expect(screen.getByText('Annullata').closest('[data-slot="badge"]')).toHaveAttribute(
      'data-tone',
      'danger',
    )
  })

  it('shows money still owed in the waiting-on-somebody tone', () => {
    renderCell('stato_pagamento', ISSUED)
    expect(screen.getByText('Da incassare').closest('[data-slot="badge"]')).toHaveAttribute(
      'data-tone',
      'gold',
    )
  })

  it('shows a collected invoice as settled, not as waiting', () => {
    renderCell('stato_pagamento', { ...ISSUED, stato_pagamento: 'incassato' })
    expect(screen.getByText('Incassato').closest('[data-slot="badge"]')).toHaveAttribute(
      'data-tone',
      'ink',
    )
  })

  /** A pill is a claim about a state, and a proforma has no collection state to claim:
   *  it reads as the plain dash the accessor already returns, never as a pill. */
  it('shows the payment column of a proforma as a plain dash, with no pill at all', () => {
    const { container } = renderCell('stato_pagamento', PROFORMA)
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(container.querySelector('[data-slot="badge"]')).toBeNull()
  })
})

/**
 * The «Cliente» column (ORB-98). Opt-in, because the same columns draw the Fatture tab
 * inside a customer's page, where every row belongs to the customer named in the title:
 * a column repeating it on each line would be noise there and information only on the
 * list page, which is the one screen that mixes customers.
 */
describe('the customer column', () => {
  const CLIENTE = { cliente: true }

  function ids(options?: InvoiceColumnOptions): string[] {
    return buildInvoiceColumns(options).map((candidate) => candidate.id ?? '')
  }

  it('is not part of the default columns', () => {
    expect(ids()).not.toContain('cliente')
  })

  it('sits right after the number when asked for', () => {
    const columns = ids(CLIENTE)
    expect(columns.indexOf('cliente')).toBe(columns.indexOf('numero') + 1)
  })

  it('reads the ragione sociale the API resolved for the row', () => {
    expect(column('cliente', CLIENTE).header).toBe('Cliente')
    expect(accessor('cliente', WITH_CUSTOMER, CLIENTE)).toBe('ACME S.r.l.')
  })

  /** `customer_ragione_sociale` is `str | None` on the server: the association always
   *  exists, the name may fail to resolve. That reads as the same dash every other
   *  empty cell shows, never as an empty string a reader could mistake for a customer
   *  with no name -- and `''`, which `ragione_sociale` can legitimately hold, reads the
   *  same way. */
  it('shows the em dash when the name did not resolve or is empty', () => {
    const unresolved = { ...ISSUED, customer_ragione_sociale: null } as Invoice
    const blank = { ...ISSUED, customer_ragione_sociale: '' } as Invoice
    expect(accessor('cliente', unresolved, CLIENTE)).toBe('—')
    expect(accessor('cliente', blank, CLIENTE)).toBe('—')
    expect(accessor('cliente', ISSUED, CLIENTE)).toBe('—')
  })

  it('renders the name as plain text and the missing name as a quiet dash', () => {
    renderCell('cliente', WITH_CUSTOMER, CLIENTE)
    expect(screen.getByText('ACME S.r.l.')).toBeInTheDocument()

    renderCell('cliente', ISSUED, CLIENTE)
    expect(screen.getByText('—').className).toContain('text-muted-foreground')
  })
})
