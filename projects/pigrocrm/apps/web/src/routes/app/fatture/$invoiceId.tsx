import { createFileRoute } from '@tanstack/react-router'
import { EntityDetailLayout } from '@/components/EntityDetailLayout'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { InvoiceActions } from '@/features/invoices/InvoiceActions'
import { InvoiceLinesEditor } from '@/features/invoices/InvoiceLinesEditor'
import { InvoiceStateBadge } from '@/features/invoices/InvoiceStateBadge'
import { formatDate, formatInvoiceNumber, formatMoney } from '@/features/invoices/format'
import { useInvoice, useInvoiceLines } from '@/features/invoices/queries'

export function InvoiceDetail() {
  const { invoiceId } = Route.useParams()
  const invoice = useInvoice(invoiceId)
  const lines = useInvoiceLines(invoiceId)

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
  // The row's own state decides, never a prop a caller chose: an issued invoice's lines
  // are immutable in the database, so offering inputs would invite an edit that cannot
  // be saved. A proforma stays editable until it is consumed.
  const readOnly = !(row.stato === 'bozza' || (row.tipo === 'proforma' && row.stato !== 'consumata'))

  return (
    <EntityDetailLayout
      title={formatInvoiceNumber(row)}
      subtitle={row.causale ?? undefined}
      entityType="invoice"
      entityId={row.id}
      actions={<InvoiceStateBadge invoice={row} />}
      overview={
        <div className="space-y-8">
          <InvoiceActions invoice={row} />

          <dl className="grid max-w-lg grid-cols-2 gap-2 text-sm">
            <dt className="text-muted-foreground">Data emissione</dt>
            <dd>{formatDate(row.data_emissione)}</dd>
            <dt className="text-muted-foreground">Scadenza</dt>
            <dd>{formatDate(row.data_scadenza)}</dd>
            <dt className="text-muted-foreground">Imponibile</dt>
            <dd>{formatMoney(row.imponibile)}</dd>
            <dt className="text-muted-foreground">Imposta</dt>
            <dd>{formatMoney(row.imposta)}</dd>
            {/* Stored but outside the total: DatiBollo declares that the issuer settled
                it virtually, so adding it here would overstate what the customer owes. */}
            <dt className="text-muted-foreground">Bollo</dt>
            <dd>{formatMoney(row.bollo)}</dd>
            <dt className="text-muted-foreground font-medium">Totale</dt>
            <dd className="font-medium">{formatMoney(row.totale)}</dd>
            {row.annullata_il !== null ? (
              <>
                <dt className="text-muted-foreground">Annullata il</dt>
                <dd>{formatDate(row.annullata_il)}</dd>
                <dt className="text-muted-foreground">Motivo</dt>
                <dd>{row.motivo_annullamento ?? '—'}</dd>
              </>
            ) : null}
          </dl>

          <section className="space-y-3">
            <h2 className="text-sm font-medium">Righe</h2>
            {lines.isError ? (
              <QueryErrorBanner error={lines.error} />
            ) : (
              <InvoiceLinesEditor invoice={row} lines={lines.data ?? []} readOnly={readOnly} />
            )}
          </section>
        </div>
      }
    />
  )
}

export const Route = createFileRoute('/app/fatture/$invoiceId')({ component: InvoiceDetail })
