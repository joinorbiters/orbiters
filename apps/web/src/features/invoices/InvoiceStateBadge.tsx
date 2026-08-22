import { Badge } from '@/components/ui/badge'
import { INVOICE_STATE_LABELS, type Invoice, type InvoiceStato } from './queries'

/** `annullata` is the one state that must read as a warning: an annulled invoice keeps
 *  its number and stays in the register, so a row that looked ordinary would be read as
 *  a live document. `bozza` and `consumata` are quiet, because neither is a claim about
 *  money owed. */
const STATE_VARIANT: Record<InvoiceStato, 'default' | 'secondary' | 'destructive'> = {
  bozza: 'secondary',
  emessa: 'default',
  annullata: 'destructive',
  confermata: 'default',
  consumata: 'secondary',
}

/** Its own file rather than living beside `buildInvoiceColumns`: eslint's
 *  `react-refresh/only-export-components` refuses a module that exports both a
 *  component and a plain function, and it is right -- fast refresh cannot tell which
 *  half changed, so an edit to the column list would remount the badge and lose its
 *  state. The other three entity screens split them the same way. */
export function InvoiceStateBadge({ invoice }: { invoice: Invoice }) {
  const stato = invoice.stato as InvoiceStato
  return <Badge variant={STATE_VARIANT[stato] ?? 'secondary'}>{INVOICE_STATE_LABELS[stato]}</Badge>
}
