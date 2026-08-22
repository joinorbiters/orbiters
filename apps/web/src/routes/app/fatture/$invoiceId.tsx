import { createFileRoute } from '@tanstack/react-router'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { formatDate, formatInvoiceNumber, formatMoney } from '@/features/invoices/format'
import { InvoiceStateBadge } from '@/features/invoices/InvoiceStateBadge'
import { useInvoice } from '@/features/invoices/queries'

/**
 * A read-only view for now. Task 19 replaces it with the full page: issue with a
 * confirmation, annul with a reason, the artefact downloads, and the produce-artifacts
 * call that follows emission.
 *
 * It exists already because the list navigates here, and a list whose rows lead nowhere
 * is worse than one with no rows: it reads as broken rather than as unfinished.
 */
function InvoiceDetail() {
  const { invoiceId } = Route.useParams()
  const invoice = useInvoice(invoiceId)

  if (invoice.isLoading) return <p className="p-8">Caricamento…</p>
  if (invoice.isError) {
    return (
      <div className="p-8">
        <QueryErrorBanner error={invoice.error} />
      </div>
    )
  }
  if (!invoice.data) return <p className="p-8">Fattura non trovata.</p>

  const row = invoice.data
  return (
    <div className="space-y-4 p-8">
      <header className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{formatInvoiceNumber(row)}</h1>
        <InvoiceStateBadge invoice={row} />
      </header>
      <dl className="grid max-w-md grid-cols-2 gap-2 text-sm">
        <dt className="text-muted-foreground">Data</dt>
        <dd>{formatDate(row.data_emissione)}</dd>
        <dt className="text-muted-foreground">Imponibile</dt>
        <dd>{formatMoney(row.imponibile)}</dd>
        <dt className="text-muted-foreground">Imposta</dt>
        <dd>{formatMoney(row.imposta)}</dd>
        <dt className="text-muted-foreground">Totale</dt>
        <dd className="font-medium">{formatMoney(row.totale)}</dd>
      </dl>
    </div>
  )
}

export const Route = createFileRoute('/app/fatture/$invoiceId')({ component: InvoiceDetail })
