import { useNavigate } from '@tanstack/react-router'
import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useCustomers } from '@/features/customers/queries'
import { useDeals } from '@/features/deals/queries'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { formatMoney, previewImponibile } from './format'
import { useCreateInvoice } from './queries'

/**
 * One line as this form holds it: three strings, because that is what an input gives
 * back, and the conversion happens once on submit.
 *
 * Narrower than `lineDraft.ts`'s `DraftLine` on purpose. That type serves the editor on
 * the detail page, which also edits units and discounts; a new document needs the three
 * fields that decide what it is worth, and the rest is a correction to make on the page
 * the owner lands on -- where `PUT /{id}/lines` can express them and this create call,
 * being a create, has nothing to clear.
 */
interface DraftRow {
  descrizione: string
  quantita: string
  prezzo_unitario: string
}

/** `InvoiceLineIn.quantita` defaults to 1 server-side; the field is pre-filled with it
 *  so the commonest line (one of something) needs no typing at all. */
function newRow(): DraftRow {
  return { descrizione: '', quantita: '1', prezzo_unitario: '' }
}

function isComplete(row: DraftRow): boolean {
  return row.descrizione.trim() !== '' && row.prezzo_unitario.trim() !== ''
}

function isStarted(row: DraftRow): boolean {
  return row.descrizione.trim() !== '' || row.prezzo_unitario.trim() !== ''
}

interface Errors {
  customer?: string
  causale?: string
  righe?: string
}

/**
 * Split out so `useCustomers` is mounted -- and therefore requested -- only while the
 * dialog is actually open, the same reasoning `features/deals/DealForm.tsx`'s
 * `CustomerPicker` documents at length. `limit: 200` mirrors it too: a one-shot cap for
 * a dropdown, not a paginated list of its own.
 */
function CustomerPicker({
  value,
  onChange,
}: {
  value: string
  onChange: (value: string) => void
}) {
  const customers = useCustomers({ limit: 200 })

  return (
    <div className="space-y-2">
      <Label htmlFor="proforma-cliente">
        Cliente
        <span className="ml-1 text-destructive">*</span>
      </Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id="proforma-cliente" className="w-full">
          <SelectValue placeholder="Seleziona un cliente…" />
        </SelectTrigger>
        <SelectContent>
          {customers.data?.items.map((customer) => (
            <SelectItem key={customer.id} value={customer.id}>
              {customer.ragione_sociale}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

/** `NO_DEAL` is a UI-only value: "no deal" is the *absence* of `deal_id` in the body,
 *  and a `Select` needs a non-empty string to represent an option. */
const NO_DEAL = 'nessuno'

/**
 * Rendered only once a customer is chosen, which is what makes the list correct rather
 * than merely short: `InvoiceService.create` calls `_check_owner`, so a deal belonging
 * to someone else is a 409, and `DealListQuery.customer_id` lets the repository -- the
 * only thing that can see a deal this page never fetched -- do the filtering.
 */
function DealPicker({
  customerId,
  value,
  onChange,
}: {
  customerId: string
  value: string
  onChange: (value: string) => void
}) {
  const deals = useDeals({ customer_id: customerId })

  return (
    <div className="space-y-2">
      <Label htmlFor="proforma-deal">Deal (facoltativo)</Label>
      <Select value={value === '' ? NO_DEAL : value} onValueChange={onChange}>
        <SelectTrigger id="proforma-deal" className="w-full">
          <SelectValue placeholder="Nessun deal" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NO_DEAL}>Nessun deal</SelectItem>
          {deals.data?.items.map((deal) => (
            <SelectItem key={deal.id} value={deal.id}>
              {deal.nome}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

/**
 * Creating a proforma from the Fatture page.
 *
 * A proforma and not a `fattura` bozza, even though `POST /api/invoices` accepts both:
 * what the owner does next is confirm it and issue it (`POST /{id}/confirm`, then
 * `POST /{id}/issue`), which is exactly the proforma's own path -- and neither shape
 * has a number until emission, so nothing here can burn one.
 *
 * `data_scadenza` is deliberately not a field. It is not on `InvoiceCreate` at all
 * (packages/core/src/pigrocrm/core/invoices/schemas.py): the due date is derived at
 * emission from the fiscal profile's `giorni_scadenza` (`InvoiceService.issue`). A
 * control for it here would have been silently dropped -- `InvoiceCreate` does not
 * forbid extra keys -- which is worse than not offering it, so the dialog says where
 * the date comes from instead.
 */
function NewProformaDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const create = useCreateInvoice()
  const [customerId, setCustomerId] = useState('')
  const [dealId, setDealId] = useState('')
  const [causale, setCausale] = useState('')
  const [note, setNote] = useState('')
  const [rows, setRows] = useState<DraftRow[]>(() => [newRow()])
  const [errors, setErrors] = useState<Errors>({})
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  function update(index: number, field: keyof DraftRow, value: string) {
    setRows((previous) =>
      previous.map((row, position) => (position === index ? { ...row, [field]: value } : row)),
    )
  }

  function chooseCustomer(value: string) {
    setCustomerId(value)
    // A deal chosen for the previous customer would be a 409 from `_check_owner`, and
    // the picker below is about to list a different set entirely.
    setDealId('')
  }

  /** What this form checks before asking, and nothing more. Everything else -- the
   *  regime's rules, the widths, whether the deal really is this customer's -- is the
   *  server's answer, rendered as it comes (see `problem` below). */
  function validate(): Errors {
    const found: Errors = {}
    if (customerId === '') found.customer = 'Scegli il cliente da fatturare.'
    if (causale.trim() === '') found.causale = 'La causale è obbligatoria.'
    if (!rows.some(isComplete)) {
      found.righe = 'Serve almeno una riga con descrizione e prezzo unitario.'
    } else if (rows.some((row) => isStarted(row) && !isComplete(row))) {
      found.righe = 'Ogni riga iniziata richiede descrizione e prezzo unitario.'
    }
    return found
  }

  function submit() {
    const found = validate()
    setErrors(found)
    setProblem(null)
    if (Object.keys(found).length > 0) return

    const body: Record<string, unknown> = {
      customer_id: customerId,
      tipo: 'proforma',
      causale: causale.trim(),
      // Only the complete rows, and each one with only the keys the user filled in.
      // An omitted optional key on a *create* is the server's own default, which is
      // what "the user did not say" means here -- unlike `InvoiceLinesEditor`, where a
      // full replacement makes an omitted key indistinguishable from an unchanged one
      // and `null` has to be explicit.
      righe: rows.filter(isComplete).map((row) => ({
        descrizione: row.descrizione.trim(),
        quantita: row.quantita.trim() === '' ? '1' : row.quantita.trim(),
        prezzo_unitario: row.prezzo_unitario.trim(),
      })),
    }
    if (dealId !== '') body.deal_id = dealId
    if (note.trim() !== '') body.note_interne = note.trim()

    create.mutate(body, {
      onSuccess: (invoice) => {
        toast.success('Proforma creata')
        onClose()
        // Straight to the document: confirming and issuing live there
        // (`InvoiceActions`), and so does correcting anything this short form does not
        // ask for.
        void navigate({ to: '/app/fatture/$invoiceId', params: { invoiceId: invoice.id } })
      },
      onError: (error) => setProblem(toProblem(error)),
    })
  }

  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Nuova proforma</DialogTitle>
          <DialogDescription>
            Una proforma non è un documento fiscale: la confermi e la emetti dalla sua
            pagina, ed è l’emissione che assegna il numero e calcola la scadenza dai
            giorni di pagamento del profilo fiscale.
          </DialogDescription>
        </DialogHeader>

        {problem ? <QueryErrorBanner error={problem} /> : null}

        <div className="space-y-4">
          <CustomerPicker value={customerId} onChange={chooseCustomer} />
          {errors.customer ? (
            <p className="text-sm text-destructive">{errors.customer}</p>
          ) : null}

          {customerId === '' ? null : (
            <DealPicker
              customerId={customerId}
              value={dealId}
              onChange={(value) => setDealId(value === NO_DEAL ? '' : value)}
            />
          )}

          <div className="space-y-2">
            <Label htmlFor="proforma-causale">
              Causale
              <span className="ml-1 text-destructive">*</span>
            </Label>
            <Input
              id="proforma-causale"
              value={causale}
              onChange={(event) => setCausale(event.target.value)}
              placeholder="Consulenza settembre 2026"
            />
            {errors.causale ? (
              <p className="text-sm text-destructive">{errors.causale}</p>
            ) : null}
          </div>

          <div className="space-y-2">
            <p className="text-sm font-medium">Righe</p>
            {rows.map((row, index) => (
              // The index is the key because a row has no identity yet -- nothing here
              // exists server-side, and rows are only ever added or removed whole.
              <div key={index} className="grid items-end gap-2 sm:grid-cols-12">
                <div className="sm:col-span-6">
                  <Input
                    aria-label={`Descrizione riga ${index + 1}`}
                    placeholder="Descrizione"
                    value={row.descrizione}
                    onChange={(event) => update(index, 'descrizione', event.target.value)}
                  />
                </div>
                <div className="sm:col-span-2">
                  <Input
                    aria-label={`Quantità riga ${index + 1}`}
                    placeholder="Quantità"
                    value={row.quantita}
                    onChange={(event) => update(index, 'quantita', event.target.value)}
                  />
                </div>
                <div className="sm:col-span-3">
                  <Input
                    aria-label={`Prezzo unitario riga ${index + 1}`}
                    placeholder="Prezzo unitario"
                    value={row.prezzo_unitario}
                    onChange={(event) => update(index, 'prezzo_unitario', event.target.value)}
                  />
                </div>
                <div className="sm:col-span-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Rimuovi riga ${index + 1}`}
                    // The last row is never removable: a document with no rows is not
                    // something this form offers (see `validate`), and an empty list
                    // would leave nothing to type into.
                    disabled={rows.length === 1}
                    onClick={() =>
                      setRows((previous) => previous.filter((_, position) => position !== index))
                    }
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              </div>
            ))}
            {errors.righe ? <p className="text-sm text-destructive">{errors.righe}</p> : null}

            <div className="flex items-center justify-between">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setRows((previous) => [...previous, newRow()])}
              >
                <Plus className="mr-2 size-4" />
                Aggiungi riga
              </Button>
              {/* Explicitly an anteprima, exactly as `InvoiceLinesEditor` labels its
                  own: the imponibile that counts is the one the service computes and
                  stores, with the regime's rules applied. */}
              <span className="text-muted-foreground text-sm">
                Anteprima imponibile: {formatMoney(previewImponibile(rows))}
              </span>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="proforma-note">Note interne (facoltative)</Label>
            <Textarea
              id="proforma-note"
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Annulla
          </Button>
          <Button onClick={submit} disabled={create.isPending}>
            {create.isPending ? 'Creazione…' : 'Crea proforma'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/**
 * The Fatture page's own entry point into creating a document.
 *
 * The dialog is *mounted* only while open rather than kept behind `open={false}`, so
 * the customer list is fetched when someone actually wants to pick from it -- the same
 * fix, for the same reason, that `DealForm`'s `CustomerPicker` documents.
 */
export function NewProformaButton() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <Button onClick={() => setOpen(true)}>
        <Plus className="mr-2 size-4" />
        Nuova fattura
      </Button>
      {open ? <NewProformaDialog onClose={() => setOpen(false)} /> : null}
    </>
  )
}
