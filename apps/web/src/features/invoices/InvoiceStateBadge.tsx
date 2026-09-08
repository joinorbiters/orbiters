import { StatusPill } from '@/components/StatusPill'
import { Badge } from '@/components/ui/badge'
import {
  INVOICE_STATE_LABELS,
  INVOICE_STATE_TONE,
  type Invoice,
  type InvoiceStato,
} from './queries'

/** Its own file rather than living beside `buildInvoiceColumns`: eslint's
 *  `react-refresh/only-export-components` refuses a module that exports both a
 *  component and a plain function, and it is right -- fast refresh cannot tell which
 *  half changed, so an edit to the column list would remount the badge and lose its
 *  state. The other three entity screens split them the same way.
 *
 *  The tone each state reads as is `INVOICE_STATE_TONE`, next to the labels in
 *  `queries.ts`, not a second table here: the state's label and the state's colour are
 *  one decision and a state added on the server must break the compile in exactly one
 *  place. */
export function InvoiceStateBadge({ invoice }: { invoice: Invoice }) {
  const stato = invoice.stato as InvoiceStato
  return (
    <span className="inline-flex items-center gap-1.5">
      <StatusPill tone={INVOICE_STATE_TONE[stato] ?? 'muted'}>
        {INVOICE_STATE_LABELS[stato]}
      </StatusPill>
      {/* The column's value is never printed. What a reader of the register needs is
          that this invoice was issued elsewhere -- so it carries no XML and no PDF
          pigroCRM produced -- and not the name of the tool it came out of, which is
          the owner's business and no part of the CRM's copy.

          A pill with no dot, deliberately: «importata» is not one of the fiscal states
          and must not read as a sixth one sitting in the same row. */}
      {invoice.importata_da != null ? (
        <Badge variant="pill" className="text-muted-foreground">
          importata
        </Badge>
      ) : null}
    </span>
  )
}
