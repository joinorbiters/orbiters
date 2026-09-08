import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import { Receipt } from 'lucide-react'
import { useState } from 'react'
import { DataTable } from '@/components/DataTable'
import { FilterChips, FilterRow } from '@/components/FilterRow'
import { PageHeader } from '@/components/PageHeader'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { buildInvoiceColumns } from '@/features/invoices/columns'
import { NewProformaButton } from '@/features/invoices/NewProformaDialog'
import { booleanSearchParam } from '@/lib/searchParams'
import {
  INVOICE_STATE_LABELS,
  useInvoices,
  type InvoiceStato,
  type InvoiceTipo,
} from '@/features/invoices/queries'

/** `tutti` is a UI-only value: the API filter is simply absent when nothing is
 *  selected, and a `Select` needs a non-empty string to represent "no filter". The
 *  state filter has no such sentinel any more -- it is a row of chips, where "no
 *  filter" is `null` (see `FilterChips`). */
const ANY = 'tutti'

const TIPI = [
  { value: ANY, label: 'Tutti i tipi' },
  { value: 'fattura', label: 'Fatture' },
  { value: 'proforma', label: 'Proforma' },
]

/** The five fiscal states, as chips, in the order `INVOICE_STATE_LABELS` declares them:
 *  that map is next to the tones and the transitions on the server, so a state added
 *  there appears here without this file changing. */
const STATI = Object.entries(INVOICE_STATE_LABELS).map(([value, label]) => ({
  value: value as InvoiceStato,
  label,
}))

/**
 * Exported so `index.test.tsx` can render the list without a router: the route
 * component below is what reads `scadute` out of the URL, and this is what draws the
 * page. The split is the same one `CustomersPage`/`PeoplePage` already make for their
 * own `?search=` term.
 */
export function InvoicesList({ scadute }: { scadute?: boolean }) {
  const navigate = useNavigate()
  const [tipo, setTipo] = useState(ANY)
  const [stato, setStato] = useState<InvoiceStato | null>(null)

  // Cast at the boundary, not in the state: `Select` deals in strings, and the type
  // option list is built from the same constants the API's literals come from, so a
  // value that is not a legal `InvoiceTipo` cannot be produced here. `stato` needs no
  // cast at all since the chips carry the literal itself.
  //
  // `scadute` comes from the URL rather than from a control, because it is a
  // drill-through and not a filter of this page's own: the operational dashboard counts
  // overdue invoices with `_overdue_predicate` in `InvoiceRepository`, and this list is
  // the same predicate evaluated on the same rows (criterion 2). Re-deciding "overdue"
  // here -- comparing `data_scadenza` against today's date in the browser -- is how the
  // count and the list start disagreeing on an invoice due today.
  const invoices = useInvoices({
    tipo: tipo === ANY ? undefined : (tipo as InvoiceTipo),
    stato: stato ?? undefined,
    scadute,
  })

  const columns = buildInvoiceColumns()

  return (
    <>
      <PageHeader
        icon={Receipt}
        title="Fatture"
        description="Una fattura si emette da un deal, da un cliente o da qui, creando una proforma da confermare ed emettere. Le proforma si distinguono dal riferimento al posto del numero: non sono documenti fiscali finché non vengono emesse."
        actions={<NewProformaButton />}
      >
        <FilterRow>
          <FilterChips
            label="Filtra per stato"
            allLabel="Tutte"
            options={STATI}
            value={stato}
            onChange={setStato}
          />

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
        </FilterRow>
      </PageHeader>

      <div className="px-8 pb-8">
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
    </>
  )
}

function InvoicesPage() {
  const { scadute } = Route.useSearch()
  return <InvoicesList scadute={scadute} />
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
