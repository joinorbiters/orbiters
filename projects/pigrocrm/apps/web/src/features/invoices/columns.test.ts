import { render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { describe, expect, it } from 'vitest'
import { buildInvoiceColumns } from './columns'
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

function accessor(id: string, row: Invoice): unknown {
  const column = buildInvoiceColumns().find((candidate) => candidate.id === id)
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
function renderCell(id: string, row: Invoice) {
  const column = buildInvoiceColumns().find((candidate) => candidate.id === id)
  if (column === undefined || typeof column.cell !== 'function') {
    throw new Error(`la colonna ${id} non ha un cell renderer`)
  }
  return render(column.cell({ row: { original: row } } as never) as ReactElement)
}

function column(id: string) {
  const found = buildInvoiceColumns().find((candidate) => candidate.id === id)
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
