import { BadgeEuro, Ban, Download, FileCheck2, RefreshCw, Send, Trash2, Undo2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useIsAdmin } from '@/lib/auth'
import { toIsoDate } from '@/lib/dates'
import {
  downloadInvoiceArtifact,
  useAnnulInvoice,
  useDeleteInvoice,
  useIssueInvoice,
  useMarkTransmitted,
  useProduceArtifacts,
  useSetPaymentState,
  type Invoice,
} from './queries'

export function InvoiceActions({
  invoice,
  onDeleted,
}: {
  invoice: Invoice
  /** Called once the server has accepted the delete: the page this bar sits on no
   *  longer exists, so the caller decides where to go (the list, in practice). */
  onDeleted?: () => void
}) {
  const [problem, setProblem] = useState<ProblemDetail | null>(null)
  const [annulOpen, setAnnulOpen] = useState(false)
  const [motivo, setMotivo] = useState('')
  // The two dates default to today, read from local parts (`toIsoDate`): late in the
  // evening the UTC route would propose tomorrow, which the server refuses.
  const [collectOpen, setCollectOpen] = useState(false)
  const [dataIncasso, setDataIncasso] = useState(() => toIsoDate(new Date()))
  const [transmitOpen, setTransmitOpen] = useState(false)
  const [dataTrasmissione, setDataTrasmissione] = useState(() => toIsoDate(new Date()))
  const isAdmin = useIsAdmin()

  const issue = useIssueInvoice(invoice.id)
  const annul = useAnnulInvoice(invoice.id)
  const artifacts = useProduceArtifacts(invoice.id)
  const payment = useSetPaymentState(invoice.id)
  const transmitted = useMarkTransmitted(invoice.id)
  const remove = useDeleteInvoice()

  const isDraftFattura = invoice.tipo === 'fattura' && invoice.stato === 'bozza'
  const isProformaReady = invoice.tipo === 'proforma' && invoice.stato === 'confermata'
  const canIssue = isDraftFattura || isProformaReady
  const isIssued = invoice.tipo === 'fattura' && invoice.stato === 'emessa'
  // What never consumed a number can go (slice 3 §4: a draft is «cancellabile»): a
  // draft fattura, and a proforma until it is consumed by the emission it precedes.
  // The server (`soft_delete`, and the CHECK behind it) refuses everything else with a
  // 409, so this mirrors the rule rather than owning it. An issued invoice is annulled.
  const canDelete = isDraftFattura || (invoice.tipo === 'proforma' && invoice.stato !== 'consumata')
  // An invoice pigroCRM imported never had its own XML rendered here: the one on file is
  // whatever the system that issued it transmitted at the time, so offering to
  // regenerate it would silently replace a legally-filed document with a
  // reconstruction. The flag is the column's presence, never its value.
  const isImported = invoice.importata_da != null
  // Collection is a fact about an issued invoice and nothing else (`set_payment_state`
  // answers 409 for every other state), so the two payment buttons only exist there.
  // A proforma is never collected and a draft is not yet a document.
  const collected = invoice.stato_pagamento === 'incassato'
  // Settable once and admin-only on the server (`mark_transmitted_externally`), and
  // meaningless for an imported invoice: the system that issued it is the one that
  // transmitted it, and the column already says so. The button follows all three.
  const canMarkTransmitted =
    isIssued && isAdmin && !isImported && invoice.trasmessa_esternamente_il === null

  /**
   * Emission and the render are two steps, deliberately.
   *
   * `issue()` is one transaction and does not produce the artefacts; the caller does.
   * That boundary exists because calling the render from inside emission made emission
   * stop being one transaction, and an artefact commit then survived a rollback.
   *
   * So a failure of the second call is **not** a failed emission. The invoice has its
   * number and is fiscally complete; it is merely unprinted, and `produce_artifacts`
   * regenerates deterministically from the frozen snapshot whenever it is called again.
   * Saying "emission failed" here would be the more dangerous lie, so the message says
   * exactly what happened and what to press.
   */
  function onIssue() {
    if (!window.confirm(`Emettere questo documento? Il numero assegnato non è più modificabile.`))
      return
    setProblem(null)
    issue.mutate(
      {},
      {
        onSuccess: (issued) => {
          toast.success('Documento emesso')
          artifacts.mutate(undefined, {
            onError: () =>
              toast.warning(
                'Documento emesso correttamente, ma PDF e XML non sono stati generati. ' +
                  'Riprova con «Rigenera documenti»: il numero resta quello.',
              ),
          })
          void issued
        },
        onError: (error) => setProblem(toProblem(error)),
      },
    )
  }

  /**
   * A soft delete, and one the person decides: `apps/mcp` deliberately has no tool for
   * it. The confirm is against a misclick, the way «Emetti» has one; there is no reason
   * to ask for, because nothing fiscal happened yet and the list is where you land.
   */
  function onDelete() {
    const what = invoice.tipo === 'proforma' ? 'questa proforma' : 'questa bozza'
    if (!window.confirm(`Eliminare ${what}? Non ha un numero, quindi non resta traccia nel registro.`))
      return
    setProblem(null)
    remove.mutate(invoice.id, {
      onSuccess: () => {
        toast.success(invoice.tipo === 'proforma' ? 'Proforma eliminata' : 'Bozza eliminata')
        onDeleted?.()
      },
      onError: (error) => setProblem(toProblem(error)),
    })
  }

  function onAnnul() {
    setProblem(null)
    annul.mutate(motivo, {
      onSuccess: () => {
        toast.success('Documento annullato. Il numero resta nel registro.')
        setAnnulOpen(false)
      },
      onError: (error) => setProblem(toProblem(error)),
    })
  }

  function onCollect() {
    setProblem(null)
    payment.mutate(
      { stato_pagamento: 'incassato', data_incasso: dataIncasso },
      {
        onSuccess: () => {
          toast.success('Incasso registrato')
          setCollectOpen(false)
        },
        onError: (error) => setProblem(toProblem(error)),
      },
    )
  }

  /**
   * The way back. A collection recorded on the wrong invoice is an ordinary mistake,
   * and the server clears the date with the state (`set_payment_state`), so undoing it
   * is one call with no dialog -- the confirm is against a misclick, nothing more.
   */
  function onUncollect() {
    if (!window.confirm('Segnare questa fattura come ancora da incassare? La data di incasso viene tolta.'))
      return
    setProblem(null)
    payment.mutate(
      { stato_pagamento: 'da_incassare', data_incasso: null },
      {
        onSuccess: () => toast.success('Fattura segnata da incassare'),
        onError: (error) => setProblem(toProblem(error)),
      },
    )
  }

  function onTransmit() {
    setProblem(null)
    transmitted.mutate(dataTrasmissione, {
      onSuccess: () => {
        toast.success('Trasmissione registrata')
        setTransmitOpen(false)
      },
      onError: (error) => setProblem(toProblem(error)),
    })
  }

  async function onDownload(kind: 'pdf' | 'xml') {
    try {
      await downloadInvoiceArtifact(invoice.id, kind)
    } catch (error) {
      toast.error(toProblem(error).detail)
    }
  }

  return (
    <div className="space-y-3">
      {problem ? <QueryErrorBanner error={problem} /> : null}

      <div className="flex flex-wrap gap-2">
        {canIssue ? (
          <Button onClick={onIssue} disabled={issue.isPending}>
            <FileCheck2 className="mr-2 size-4" />
            Emetti
          </Button>
        ) : null}

        {isIssued ? (
          <>
            {/* The state of the money comes first among an issued invoice's actions:
                marking a collection is the thing done most often to an invoice after
                it leaves, and the one the list's «Pagamento» pill is waiting for. */}
            {collected ? (
              <Button variant="outline" onClick={onUncollect} disabled={payment.isPending}>
                <Undo2 className="mr-2 size-4" />
                Segna da incassare
              </Button>
            ) : (
              <Button onClick={() => setCollectOpen(true)} disabled={payment.isPending}>
                <BadgeEuro className="mr-2 size-4" />
                Segna incassata
              </Button>
            )}
            {canMarkTransmitted ? (
              <Button
                variant="outline"
                onClick={() => setTransmitOpen(true)}
                disabled={transmitted.isPending}
              >
                <Send className="mr-2 size-4" />
                Segna trasmessa
              </Button>
            ) : null}
            <Button variant="outline" onClick={() => void onDownload('pdf')}>
              <Download className="mr-2 size-4" />
              PDF
            </Button>
            {isImported ? null : (
              <Button variant="outline" onClick={() => void onDownload('xml')}>
                <Download className="mr-2 size-4" />
                XML FatturaPA
              </Button>
            )}
            {isImported ? null : (
              <Button
                variant="outline"
                onClick={() =>
                  artifacts.mutate(undefined, {
                    onSuccess: () => toast.success('Documenti rigenerati'),
                    onError: (error) => toast.error(toProblem(error).detail),
                  })
                }
                disabled={artifacts.isPending}
              >
                <RefreshCw className="mr-2 size-4" />
                Rigenera documenti
              </Button>
            )}
            <Button variant="destructive" onClick={() => setAnnulOpen(true)}>
              <Ban className="mr-2 size-4" />
              Annulla
            </Button>
          </>
        ) : null}

        {invoice.tipo === 'proforma' && invoice.stato !== 'consumata' ? (
          <Button variant="outline" onClick={() => void onDownload('pdf')}>
            <Download className="mr-2 size-4" />
            PDF proforma
          </Button>
        ) : null}

        {canDelete ? (
          <Button variant="destructive" onClick={onDelete} disabled={remove.isPending}>
            <Trash2 className="mr-2 size-4" />
            {invoice.tipo === 'proforma' ? 'Elimina proforma' : 'Elimina bozza'}
          </Button>
        ) : null}
      </div>

      <Dialog open={collectOpen} onOpenChange={setCollectOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Registra l&apos;incasso</DialogTitle>
          </DialogHeader>
          {/* The date is required by the server («un incasso senza data non è un
              incasso»): the day the money arrived is what the cash view and the fiscal
              estimate read, so it is asked for here rather than assumed to be today. */}
          <p className="text-muted-foreground text-sm">
            La fattura passa a «Incassato» e la data entra nella vista economica dell&apos;anno
            in cui cade. Si può tornare indietro.
          </p>
          <div className="space-y-2">
            <Label htmlFor="data-incasso">Data incasso</Label>
            <Input
              id="data-incasso"
              type="date"
              required
              value={dataIncasso}
              onChange={(event) => setDataIncasso(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCollectOpen(false)}>
              Chiudi
            </Button>
            <Button onClick={onCollect} disabled={payment.isPending || dataIncasso === ''}>
              Registra incasso
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={transmitOpen} onOpenChange={setTransmitOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Segna come trasmessa</DialogTitle>
          </DialogHeader>
          {/* Once. This is the column that tells an invoice that never left -- still
              annullable -- from one already deposited with the Agenzia delle Entrate,
              and it stays frozen for exactly that reason (`mark_transmitted_externally`). */}
          <p className="text-muted-foreground text-sm">
            Registra che l&apos;XML è stato consegnato all&apos;intermediario o allo SDI fuori da
            PigroCRM. Non si può annullare.
          </p>
          <div className="space-y-2">
            <Label htmlFor="data-trasmissione">Data di trasmissione</Label>
            <Input
              id="data-trasmissione"
              type="date"
              required
              value={dataTrasmissione}
              onChange={(event) => setDataTrasmissione(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTransmitOpen(false)}>
              Chiudi
            </Button>
            <Button
              onClick={onTransmit}
              disabled={transmitted.isPending || dataTrasmissione === ''}
            >
              Segna trasmessa
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={annulOpen} onOpenChange={setAnnulOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Annulla documento</DialogTitle>
          </DialogHeader>
          {/* Annulment is not deletion: the number stays in the register and the row
              stays readable, because a fiscal register with a hole in it is a problem
              with the tax authority. The reason is required for the same purpose --
              it is what the document's own history will say later. */}
          <p className="text-muted-foreground text-sm">
            Il numero resta nel registro e il documento resta consultabile. Per correggere
            un errore si emette un nuovo documento, non si modifica questo.
          </p>
          <div className="space-y-2">
            <Label htmlFor="motivo-annullamento">Motivo</Label>
            <Textarea
              id="motivo-annullamento"
              value={motivo}
              rows={3}
              onChange={(event) => setMotivo(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAnnulOpen(false)}>
              Chiudi
            </Button>
            <Button variant="destructive" onClick={onAnnul} disabled={annul.isPending}>
              Annulla documento
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
