import type { ColumnDef } from '@tanstack/react-table'
import type { DataTableFeatures } from '@/components/DataTable'
import { InvoiceStateBadge } from './InvoiceStateBadge'
import { formatDate, formatInvoiceNumber, formatMoney } from './format'
import {
  INVOICE_TYPE_LABELS,
  PAYMENT_STATE_LABELS,
  type Invoice,
} from './queries'

const EMPTY = '—'

export function buildInvoiceColumns(): ColumnDef<DataTableFeatures, Invoice>[] {
  return [
    {
      header: 'Numero',
      id: 'numero',
      // A fiscal number for an invoice, a reference for a proforma. The two are
      // different kinds of identity, not two spellings of one -- which is why
      // `formatInvoiceNumber` cannot derive a reference from a number.
      accessorFn: (row) => formatInvoiceNumber(row),
    },
    {
      header: 'Tipo',
      id: 'tipo',
      accessorFn: (row) => INVOICE_TYPE_LABELS[row.tipo as keyof typeof INVOICE_TYPE_LABELS],
    },
    {
      header: 'Stato',
      id: 'stato',
      cell: ({ row }) => <InvoiceStateBadge invoice={row.original} />,
    },
    {
      header: 'Data',
      id: 'data_emissione',
      accessorFn: (row) => formatDate(row.data_emissione),
    },
    {
      header: 'Totale',
      id: 'totale',
      // `formatMoney` parses the decimal string into integer cents; nothing here ever
      // sees a float.
      accessorFn: (row) => formatMoney(row.totale),
    },
    {
      header: 'Pagamento',
      id: 'stato_pagamento',
      // A proforma is never collected. Showing "Da incassare" beside something nobody
      // owes is the kind of small lie a fiscal list should not tell, so it reads as
      // absent rather than as unpaid.
      accessorFn: (row) =>
        row.tipo === 'proforma'
          ? EMPTY
          : PAYMENT_STATE_LABELS[row.stato_pagamento as keyof typeof PAYMENT_STATE_LABELS],
    },
  ]
}
