import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { DataTable } from '@/components/DataTable'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { buildInvoiceColumns } from '@/features/invoices/columns'
import { booleanSearchParam } from '@/lib/searchParams'
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
  const { scadute } = Route.useSearch()
  const [tipo, setTipo] = useState(ANY)
  const [stato, setStato] = useState(ANY)

  // Cast at the boundary, not in the state: `Select` deals in strings, and the two
  // option lists are built from the same constants the API's literals come from, so a
  // value that is not a legal `InvoiceTipo`/`InvoiceStato` cannot be produced here.
  //
  // `scadute` comes from the URL rather than from a control, because it is a
  // drill-through and not a filter of this page's own: the operational dashboard counts
  // overdue invoices with `_overdue_predicate` in `InvoiceRepository`, and this list is
  // the same predicate evaluated on the same rows (criterion 2). Re-deciding "overdue"
  // here -- comparing `data_scadenza` against today's date in the browser -- is how the
  // count and the list start disagreeing on an invoice due today.
  const invoices = useInvoices({
    tipo: tipo === ANY ? undefined : (tipo as InvoiceTipo),
    stato: stato === ANY ? undefined : (stato as InvoiceStato),
    scadute,
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

      {scadute === true && (
        <p
          role="status"
          className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm"
        >
          <span>
            <strong>Scadute e non incassate</strong> — solo le fatture emesse la cui scadenza è
            passata e che non risultano incassate. Togli il filtro per vedere tutte le fatture.
          </span>
          <Button variant="outline" size="sm" asChild>
            <Link to="/app/fatture" search={{}}>
              Rimuovi il filtro
            </Link>
          </Button>
        </p>
      )}

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

export const Route = createFileRoute('/app/fatture/')({
  component: InvoicesPage,
  // Declared so the operational dashboard can link here with its "scaduto e non incassato"
  // drill-through: `<Link to={...} search={...} />` is typed against this function's
  // *return* type. `scadute` is the only search param this list reads.
  validateSearch: (search: Record<string, unknown>): { scadute?: boolean } => ({
    scadute: booleanSearchParam(search.scadute),
  }),
})
