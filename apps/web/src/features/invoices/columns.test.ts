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
