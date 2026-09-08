import { useState } from 'react'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Button } from '@/components/ui/button'
import { EmailComposer } from './EmailComposer'
import { EmailThread } from './EmailThread'
import { STATE_HEADING } from './draftStates'
import { useDraftsForEntity } from './draftQueries'
import { useGmailMessages, type GmailEntityType, type GmailMessageRead } from './queries'

/** The most recent instant in a thread. Computed rather than read off the last element:
 *  the API's ordering is `(gmail_thread_id, internal_date)`, which this code should not
 *  have to depend on to put the live conversation at the top. */
function lastActivity(thread: GmailMessageRead[]): number {
  return Math.max(...thread.map((message) => new Date(message.internal_date).getTime()))
}

function byThread(messages: GmailMessageRead[]): [string, GmailMessageRead[]][] {
  const grouped = new Map<string, GmailMessageRead[]>()
  for (const message of messages) {
    const bucket = grouped.get(message.gmail_thread_id) ?? []
    bucket.push(message)
    grouped.set(message.gmail_thread_id, bucket)
  }
  // Most recently active conversation first: that is the one being worked on. Within a
  // thread the order is left as the API returned it -- oldest first -- because a
  // conversation reads forwards.
  return [...grouped.entries()].sort((a, b) => lastActivity(b[1]) - lastActivity(a[1]))
}

/**
 * The address a reply would go to, from the most recent message on this scheda.
 *
 * Read off the correspondence already on screen rather than from a second endpoint: for
 * a message we received, the counterpart is who sent it; for one we sent, it is who we
 * sent it to. An empty answer is fine -- «A» is then a field the person fills in, which
 * is what it was going to be anyway on a scheda with no history.
 */
function replyTo(messages: GmailMessageRead[]): string[] {
  const newest = [...messages].sort(
    (a, b) => new Date(b.internal_date).getTime() - new Date(a.internal_date).getTime(),
  )[0]
  if (!newest) return []
  return newest.direction === 'inbound' ? [newest.from_address] : [...newest.to_addresses]
}

/**
 * The Email tab on a customer, a person or a deal.
 *
 * Reads the stored mirror and nothing else: there is no parameter here that reaches
 * Gmail (spec 8.2), so this tab works with the mailbox disconnected and costs nothing
 * against anybody's quota. The same message is filed against the person, their customer
 * and that customer's live deals, so the three tabs are three questions to one endpoint
 * rather than three different features.
 *
 * The drafts sit *above* the correspondence, not inside it. An unsent draft is not part
 * of the conversation the client has seen, and putting it in the thread would show them
 * a message that never left -- the same "il CRM crede una cosa diversa da quella che è
 * successa" this slice exists to remove, in the one place a person looks to find out
 * what was said.
 */
export function EmailTab({
  entityType,
  entityId,
}: {
  entityType: GmailEntityType
  entityId: string
}) {
  const messages = useGmailMessages({ entityType, entityId })
  const drafts = useDraftsForEntity({ entityType, entityId })
  // `null` is closed; `undefined` inside the tuple is «Scrivi» -- a composer with no row
  // behind it yet. The two are different states and a single `string | null` could not
  // tell them apart.
  const [composing, setComposing] = useState<{ draftId?: string } | null>(null)

  // The failure branch first. On an error `isPending` is false while `data` is still
  // undefined, so a `isPending || !data` guard would answer a failed request with
  // «Caricamento…» forever -- and the branch below it would be unreachable. An empty
  // tab and a request that never arrived are two different claims, and making the
  // second one look like the first is the defect `QueryErrorBanner` exists for.
  if (messages.isError) return <QueryErrorBanner error={messages.error} />
  if (messages.isPending || !messages.data)
    return <p className="text-muted-foreground">Caricamento…</p>

  if (composing !== null) {
    return (
      <EmailComposer
        entityType={entityType}
        entityId={entityId}
        draftId={composing.draftId}
        defaultTo={replyTo(messages.data)}
        onClose={() => setComposing(null)}
      />
    )
  }

  const pending = (drafts.data?.items ?? []).filter((item) => item.send_state !== 'inviato')

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-muted-foreground">Corrispondenza</h3>
        <Button type="button" size="sm" onClick={() => setComposing({})}>
          Scrivi
        </Button>
      </div>

      {/* Deliberately not gated on `drafts.isError`: a drafts read that failed must not
          take the correspondence down with it. The banner says what could not be read,
          and the thread below is still the thing the person came for. */}
      {drafts.isError && <QueryErrorBanner error={drafts.error} />}

      {pending.length > 0 && (
        <ul className="divide-y rounded-lg border">
          {pending.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className={
                  'flex w-full items-center justify-between gap-3 px-3 py-2 ' +
                  'text-left text-sm hover:bg-muted'
                }
                onClick={() => setComposing({ draftId: item.id })}
              >
                <span>{item.subject === '' ? '(senza oggetto)' : item.subject}</span>
                <span className="text-muted-foreground">{STATE_HEADING[item.send_state]}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {messages.data.length === 0 ? (
        <p className="text-muted-foreground">
          Nessuna email sincronizzata per questa scheda. Le conversazioni compaiono quando un
          indirizzo di questa scheda è presente in anagrafica e il sync è stato eseguito.
        </p>
      ) : (
        byThread(messages.data).map(([threadId, thread]) => (
          <EmailThread key={threadId} messages={thread} />
        ))
      )}
    </div>
  )
}
