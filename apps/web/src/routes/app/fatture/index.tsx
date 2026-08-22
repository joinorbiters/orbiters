import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { DataTable } from '@/components/DataTable'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { buildInvoiceColumns } from '@/features/invoices/columns'
import {
  INVOICE_STATE_LABELS,
  useInvoices,
  type InvoiceStato,
  type InvoiceTipo,
} from '@/features/invoices/queries'

/** `tutti` is a UI-only value: the API filter is simply absent when nothing is
 *  selected, and a `Select` needs a non-empty string to represent "no filter". */
const ANY = 'tutti'

const TIPI = [
  { value: ANY, label: 'Tutti i tipi' },
  { value: 'fattura', label: 'Fatture' },
  { value: 'proforma', label: 'Proforma' },
]

const STATI = [
  { value: ANY, label: 'Tutti gli stati' },
  ...Object.entries(INVOICE_STATE_LABELS).map(([value, label]) => ({ value, label })),
]

function InvoicesPage() {
  const navigate = useNavigate()
  const [tipo, setTipo] = useState(ANY)
  const [stato, setStato] = useState(ANY)

  // Cast at the boundary, not in the state: `Select` deals in strings, and the two
  // option lists are built from the same constants the API's literals come from, so a
  // value that is not a legal `InvoiceTipo`/`InvoiceStato` cannot be produced here.
  const invoices = useInvoices({
    tipo: tipo === ANY ? undefined : (tipo as InvoiceTipo),
    stato: stato === ANY ? undefined : (stato as InvoiceStato),
  })

  const columns = buildInvoiceColumns()

  return (
    <div className="p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Fatture</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Una fattura si emette da un deal o da un cliente. Le proforma si distinguono
          dal riferimento al posto del numero: non sono documenti fiscali finché non
          vengono emesse.
        </p>
      </header>

      <div className="mb-4 flex gap-3">
        <Select value={tipo} onValueChange={setTipo}>
          <SelectTrigger className="w-48" aria-label="Filtra per tipo">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {TIPI.map((entry) => (
              <SelectItem key={entry.value} value={entry.value}>
                {entry.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={stato} onValueChange={setStato}>
          <SelectTrigger className="w-48" aria-label="Filtra per stato">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATI.map((entry) => (
              <SelectItem key={entry.value} value={entry.value}>
                {entry.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <DataTable
        columns={columns}
        data={invoices.data?.items ?? []}
        isLoading={invoices.isLoading}
        isError={invoices.isError}
        error={invoices.error}
        onRowClick={(row) =>
          void navigate({ to: '/app/fatture/$invoiceId', params: { invoiceId: row.id } })
        }
        emptyMessage="Nessuna fattura."
      />
    </div>
  )
}

export const Route = createFileRoute('/app/fatture/')({ component: InvoicesPage })
