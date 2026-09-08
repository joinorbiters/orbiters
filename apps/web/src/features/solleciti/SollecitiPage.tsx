import { MailWarning } from 'lucide-react'
import { useState } from 'react'
import { DataTable } from '@/components/DataTable'
import { PageHeader } from '@/components/PageHeader'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { EmailComposer } from '@/features/gmail/EmailComposer'
import { sollecitiColumns } from './columns'
import { useCandidates, useCreateReminder } from './queries'

/**
 * The solleciti list, where the work is the list and not the button.
 *
 * Acme chose what to chase with `emailSentCount > 0` -- "is this the second email" --
 * with no due date, no interval and no ceiling anywhere. Everything that makes this list
 * legitimate lives on the server: the due date is what makes a reminder legitimate at
 * all, the interval is what makes it bearable, and the ceiling of three is what stops a
 * disputed invoice becoming an automated persecution. This screen renders that answer
 * and does not recompute any part of it.
 *
 * **Preparing is not sending.** «Prepara sollecito» writes the reminder row and its
 * draft and sends nothing (spec 8.3); the composer then opens on that draft so the
 * person reads the letter that will go out in their name before it goes. The send is the
 * same single path every other email uses.
 *
 * **There is no bulk action, and that is a decision rather than a missing feature**
 * (spec 7.2). A reminder is a commercial act: it goes to a paying client, in the owner's
 * name, over a debt they may already dispute. What would have to exist for this to be
 * safe to automate -- a per-customer opt-in, a log of runs that sent nothing, an instant
 * kill switch -- does not exist, so this slice asks a person every time. No «invia
 * tutti», and no row checkboxes to build one out of.
 */
export function SollecitiPage() {
  const candidates = useCandidates()
  const createReminder = useCreateReminder()
  // Which draft the composer is open on, and which customer it belongs to. Kept together
  // because they are one fact: the reminder that was just prepared. Reading the customer
  // back out of the row list at render time would break the moment the invalidation
  // below removes that row -- which it does, immediately, and by design.
  const [reviewing, setReviewing] = useState<{ draftId: string; customerId: string } | null>(null)
  const [pendingId, setPendingId] = useState<string | null>(null)

  // The failure branch first, always. On an error `isPending` is false while `data` is
  // still undefined, so a single `isPending || !data` guard answers a failed read with a
  // spinner that never resolves -- and an empty table and a request that never arrived
  // are two different claims about somebody's unpaid invoices.
  if (candidates.isError)
    return (
      <div className="px-8 py-6">
        <QueryErrorBanner error={candidates.error} />
      </div>
    )
  if (candidates.isPending || !candidates.data)
    return <p className="px-8 py-6 text-muted-foreground">Caricamento…</p>

  const rows = candidates.data.items

  if (reviewing !== null) {
    return (
      <>
        {/* Still the Solleciti page, and still says so: the title states what this
            screen is *for* right now, which is reading a letter before it goes. There
            is no primary action in the header because the action lives in the composer
            -- «Invia» belongs next to the text it sends. */}
        <PageHeader
          icon={MailWarning}
          title="Sollecito da rivedere"
          description="Leggilo, correggilo se serve, e premi Invia quando è come lo vuoi tu."
        />
        <div className="space-y-4 px-8 pb-8">
          {/* Stays a paragraph rather than folding into the header's description: the
              emphasis is the point -- «preparare non è inviare» is this screen's whole
              safety story -- and a `description` is a plain string. */}
          <p role="status" className="text-sm text-muted-foreground">
            Il sollecito è stato preparato e <strong>non è stato inviato</strong>.
          </p>
          <EmailComposer
            entityType="customer"
            entityId={reviewing.customerId}
            draftId={reviewing.draftId}
            onClose={() => setReviewing(null)}
          />
        </div>
      </>
    )
  }

  return (
    <>
      {/* No primary action in the header, deliberately: preparing a reminder is a
          per-row act (see the «no bulk action» paragraph above), so the only button on
          this screen is the one in the row it belongs to. */}
      <PageHeader
        icon={MailWarning}
        title="Solleciti"
        description="Fatture scadute da più di una settimana, non ancora saldate, senza un sollecito recente e sotto il tetto dei tre. Preparare il sollecito non lo invia: la bozza si apre per la revisione."
      />

      <div className="space-y-4 px-8 pb-8">
        {/* The mutation's own error, never copied into component state: a refused
            preparation followed by a successful one must not print success under a banner
            still claiming the opposite. */}
        {createReminder.isError && <QueryErrorBanner error={createReminder.error} />}

        {rows.length === 0 ? (
          <p className="text-muted-foreground">
            Nessuna fattura da sollecitare. È la lista che costa fatica a costruire, non il
            pulsante da premere.
          </p>
        ) : (
          <DataTable
            columns={sollecitiColumns((invoiceId) => {
              const candidate = rows.find((row) => row.invoice_id === invoiceId)
              if (candidate === undefined) return
              setPendingId(invoiceId)
              createReminder.mutate(invoiceId, {
                onSuccess: (reminder) => {
                  setPendingId(null)
                  // `email_draft_id` is nullable on the schema and never null in practice
                  // for a reminder this endpoint just created -- but a composer opened on
                  // `''` would ask the API for a draft that cannot exist, so the absence is
                  // handled by not opening rather than by trusting the shape.
                  if (reminder.email_draft_id !== null) {
                    setReviewing({
                      draftId: reminder.email_draft_id,
                      customerId: candidate.customer_id,
                    })
                  }
                },
                onError: () => setPendingId(null),
              })
            }, pendingId)}
            data={rows}
          />
        )}
      </div>
    </>
  )
}
