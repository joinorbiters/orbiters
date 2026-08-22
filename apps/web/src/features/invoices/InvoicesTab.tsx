import { useNavigate } from '@tanstack/react-router'
import { DataTable } from '@/components/DataTable'
import { buildInvoiceColumns } from './columns'
import { useInvoicesForOwner, type InvoiceOwner } from './queries'

/**
 * The Fatture tab on a customer's or a deal's detail page.
 *
 * It reads through `useInvoicesForOwner`, which is a thin wrapper over the same hook
 * the list page uses, so both share one cache entry and one query-key shape: an invoice
 * issued from here appears on the list page without a second round trip, and the two
 * screens cannot drift into disagreeing about the same rows.
 */
export function InvoicesTab({ owner }: { owner: InvoiceOwner }) {
  const navigate = useNavigate()
  const invoices = useInvoicesForOwner(owner)

  return (
    <DataTable
      columns={buildInvoiceColumns()}
      data={invoices.data?.items ?? []}
      isLoading={invoices.isLoading}
      isError={invoices.isError}
      error={invoices.error}
      onRowClick={(row) =>
        void navigate({ to: '/app/fatture/$invoiceId', params: { invoiceId: row.id } })
      }
      emptyMessage="Nessuna fattura."
    />
  )
}
