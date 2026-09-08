import type { ColumnDef } from '@tanstack/react-table'
import { DateCell, MoneyCell, NumberCell } from '@/components/cells'
import type { DataTableFeatures } from '@/components/DataTable'
import { Button } from '@/components/ui/button'
import { formatMoneyValue } from '@/features/time/columns'
import { formatIsoDateItalian } from '@/lib/dates'
import type { SollecitoCandidate } from './queries'

const EMPTY = '—'

/**
 * The columns are the work.
 *
 * Crossing due dates against payments against what has already gone out is the laborious
 * part of chasing money; pressing a button never was. So every column here answers a
 * question somebody would otherwise answer by hand, and the last one is the button.
 *
 * `importo` goes through `formatMoneyValue` -- the same formatter the timesheet and the
 * costs table use -- rather than a fourth private copy. Money is `Numeric(12, 2)` on the
 * server and reaches here as a decimal string; nothing in this file adds, compares or
 * accumulates it, so the only conversion is ICU grouping the digits of a figure the API
 * already frozen.
 *
 * TanStack Table v9: `ColumnDef<DataTableFeatures, T>`, not v8's bare `ColumnDef<T>` --
 * see `components/DataTable.tsx` for why this codebase is on the rewrite rather than on
 * the deprecated v8 shim.
 */
export function sollecitiColumns(
  onPrepare: (invoiceId: string) => void,
  pendingId: string | null,
): ColumnDef<DataTableFeatures, SollecitoCandidate>[] {
  return [
    { accessorKey: 'numero', header: 'Fattura' },
    { accessorKey: 'cliente', header: 'Cliente' },
    {
      id: 'giorni_di_ritardo',
      header: 'Giorni di ritardo',
      accessorFn: (row) => String(row.giorni_di_ritardo),
      // A count, so it goes on the right with the amount: this table is read by
      // scanning down the two numeric columns for the worst row.
      meta: { align: 'right' },
      cell: ({ row }) => <NumberCell>{row.original.giorni_di_ritardo}</NumberCell>,
    },
    {
      id: 'importo',
      header: 'Importo',
      accessorFn: (row) => formatMoneyValue(row.importo),
      meta: { align: 'right' },
      cell: ({ row }) => <MoneyCell>{formatMoneyValue(row.original.importo)}</MoneyCell>,
    },
    {
      id: 'ultimo_sollecito_il',
      header: 'Ultimo sollecito',
      accessorFn: (row) =>
        row.ultimo_sollecito_il === null ? EMPTY : formatIsoDateItalian(row.ultimo_sollecito_il),
      cell: ({ row }) => <DateCell value={row.original.ultimo_sollecito_il} />,
    },
    {
      id: 'prossimo_livello',
      header: 'Prossimo',
      // The tone the next letter will carry, derived on the server from what actually
      // *left* rather than from how many rows exist -- so an unsent draft can never make
      // the next reminder open with «nonostante il precedente sollecito».
      accessorFn: (row) => `${row.prossimo_livello}° sollecito`,
    },
    {
      id: 'risposta',
      header: 'Risposta',
      // A reply is not a payment, and sometimes the reply is exactly what needs chasing.
      // So the candidate stays on the list; it says so, and the server sinks it to the
      // bottom. `null` here means the mailbox is disconnected or nothing was found --
      // «non lo sappiamo», which is why it renders as a dash and not as "nessuna
      // risposta".
      accessorFn: (row) =>
        row.ultima_risposta_il === null
          ? EMPTY
          : `ha risposto il ${formatIsoDateItalian(row.ultima_risposta_il)}`,
    },
    {
      id: 'azione',
      header: '',
      cell: ({ row }) => (
        <Button
          type="button"
          size="sm"
          disabled={pendingId === row.original.invoice_id}
          onClick={() => onPrepare(row.original.invoice_id)}
        >
          Prepara sollecito
        </Button>
      ),
    },
  ]
}
