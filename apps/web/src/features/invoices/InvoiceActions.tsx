import { Download, FileCheck2, Ban, RefreshCw } from 'lucide-react'
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
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { toProblem, type ProblemDetail } from '@/lib/api'
import {
  downloadInvoiceArtifact,
  useAnnulInvoice,
  useIssueInvoice,
  useProduceArtifacts,
  type Invoice,
} from './queries'

export function InvoiceActions({ invoice }: { invoice: Invoice }) {
  const [problem, setProblem] = useState<ProblemDetail | null>(null)
  const [annulOpen, setAnnulOpen] = useState(false)
  const [motivo, setMotivo] = useState('')

  const issue = useIssueInvoice(invoice.id)
  const annul = useAnnulInvoice(invoice.id)
  const artifacts = useProduceArtifacts(invoice.id)

  const isDraftFattura = invoice.tipo === 'fattura' && invoice.stato === 'bozza'
  const isProformaReady = invoice.tipo === 'proforma' && invoice.stato === 'confermata'
  const canIssue = isDraftFattura || isProformaReady
  const isIssued = invoice.tipo === 'fattura' && invoice.stato === 'emessa'
  // An invoice pigroCRM imported never had its own XML rendered here: the one on file is
  // whatever the system that issued it transmitted at the time, so offering to
  // regenerate it would silently replace a legally-filed document with a
  // reconstruction. The flag is the column's presence, never its value.
  const isImported = invoice.importata_da != null

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
      </div>

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
