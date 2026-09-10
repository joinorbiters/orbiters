import type { ColumnDef } from '@tanstack/react-table'
import { DateCell, MoneyCell } from '@/components/cells'
import type { DataTableFeatures } from '@/components/DataTable'
import { StatusPill } from '@/components/StatusPill'
import { InvoiceStateBadge } from './InvoiceStateBadge'
import { formatDate, formatInvoiceNumber, formatMoney } from './format'
import {
  INVOICE_TYPE_LABELS,
  PAYMENT_STATE_LABELS,
  PAYMENT_STATE_TONE,
  type Invoice,
  type StatoPagamento,
} from './queries'

const EMPTY = '—'

/**
 * `cliente` adds the «Cliente» column (ORB-98). Opt-in rather than always there because
 * the same columns draw two screens: the list page, which mixes every customer's
 * invoices and is where a row has to say whose it is, and the Fatture tab inside a
 * customer's or a deal's page, where every row belongs to the customer already named in
 * the title and the column would only repeat it on each line.
 */
export interface InvoiceColumnOptions {
  cliente?: boolean
}

/**
 * The name the API resolved for the row, or the dash. `customer_ragione_sociale` is
 * `str | None` on the server: the association always exists (`customer_id` is NOT NULL),
 * the name may fail to resolve, and that reads as the same em dash every other empty
 * cell shows rather than as an empty string a reader could take for a nameless customer.
 * `''` gets the same dash: `ragione_sociale` is a `SafeStr` with no minimum length, so an
 * empty name is a value the column can legitimately hold, and a blank cell would read as
 * a rendering fault rather than as what it is.
 */
function customerName(row: Invoice): string {
  const name = row.customer_ragione_sociale
  return name === null || name === undefined || name === '' ? EMPTY : name
}

export function buildInvoiceColumns(
  options: InvoiceColumnOptions = {},
): ColumnDef<DataTableFeatures, Invoice>[] {
  const cliente: ColumnDef<DataTableFeatures, Invoice>[] = options.cliente
    ? [
        {
          header: 'Cliente',
          id: 'cliente',
          accessorFn: (row) => customerName(row),
          // Plain text, like «Tipo»: the table is auto-layout and `TableCell` already
          // says `whitespace-nowrap`, so a long name widens its column and the table
          // scrolls inside its frame, the way every other text column here behaves. A
          // `truncate` on an inline span in a `<td>` with no width would promise an
          // ellipsis the DOM cannot deliver.
          cell: ({ row }) => {
            const name = customerName(row.original)
            return name === EMPTY ? <span className="text-muted-foreground">{EMPTY}</span> : name
          },
        },
      ]
    : []

  return [
    {
      header: 'Numero',
      id: 'numero',
      // A fiscal number for an invoice, a reference for a proforma. The two are
      // different kinds of identity, not two spellings of one -- which is why
      // `formatInvoiceNumber` cannot derive a reference from a number.
      accessorFn: (row) => formatInvoiceNumber(row),
    },
    ...cliente,
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
      // The accessor keeps the formatted string -- it is what a future sort or export
      // reads, and it is what this column's own tests assert -- while `cell` adds the
      // calendar icon the reference puts before every date (design spec §4). `DateCell`
      // formats the raw ISO value itself, through `lib/dates.ts`, which renders the
      // identical string this accessor does.
      accessorFn: (row) => formatDate(row.data_emissione),
      cell: ({ row }) => <DateCell value={row.original.data_emissione} />,
    },
    {
      header: 'Totale',
      id: 'totale',
      // `formatMoney` parses the decimal string into integer cents; nothing here ever
      // sees a float. `meta.align` right-aligns the header over the digits as well --
      // `MoneyCell` alone could only align what is inside the cell.
      accessorFn: (row) => formatMoney(row.totale),
      meta: { align: 'right' },
      cell: ({ row }) => <MoneyCell>{formatMoney(row.original.totale)}</MoneyCell>,
    },
    {
      header: 'Pagamento',
      id: 'stato_pagamento',
      // A proforma is never collected. Showing "Da incassare" beside something nobody
      // owes is the kind of small lie a fiscal list should not tell, so it reads as
      // absent rather than as unpaid -- and as the plain dash, never as a pill: a pill
      // is a claim about a state, and there is no state here to claim.
      accessorFn: (row) =>
        row.tipo === 'proforma'
          ? EMPTY
          : PAYMENT_STATE_LABELS[row.stato_pagamento as keyof typeof PAYMENT_STATE_LABELS],
      cell: ({ row }) => {
        if (row.original.tipo === 'proforma') {
          return <span className="text-muted-foreground">{EMPTY}</span>
        }
        // Both maps are total over `StatoPagamento`, so neither read takes a fallback:
        // one would be a branch the types make unreachable.
        const stato = row.original.stato_pagamento as StatoPagamento
        return <StatusPill tone={PAYMENT_STATE_TONE[stato]}>{PAYMENT_STATE_LABELS[stato]}</StatusPill>
      },
    },
  ]
}
