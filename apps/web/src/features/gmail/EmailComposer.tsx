import { useEffect, useRef, useState } from 'react'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import type { DocumentOwner } from '@/features/documents/queries'
import { AttachmentPicker } from './AttachmentPicker'
import {
  isEditable,
  useCreateDraft,
  useDraft,
  useReconcileDraft,
  useSendDraft,
  useUpdateDraft,
} from './draftQueries'
import {
  parseAddresses,
  promisesAnAttachmentItDoesNotHave,
  STATE_HEADING,
  STATE_HELP,
} from './draftStates'
import type { GmailEntityType } from './queries'

/** Long enough that a sentence is one save rather than forty, short enough that closing
 *  the tab mid-thought loses at most that much. */
const AUTOSAVE_MS = 600

interface Props {
  entityType: GmailEntityType
  entityId: string
  /** An existing draft to reopen. Absent means "a new one", and the row is created on the
   *  first save rather than on open -- opening the composer and closing it again must not
   *  leave an empty draft behind. */
  draftId?: string
  /** Prefills «A» for a new draft. The Email tab passes the counterpart of the most
   *  recent message, which is the address a reply is nearly always going to. */
  defaultTo?: string[]
  onClose: () => void
}

function ownerFor(entityType: GmailEntityType, entityId: string): DocumentOwner | null {
  if (entityType === 'customer') return { customerId: entityId }
  if (entityType === 'deal') return { dealId: entityId }
  // A document belongs to a customer XOR a deal (`ck_documents_customer_xor_deal`), so a
  // person's composer has nothing to offer -- and says so, rather than showing an empty
  // list that reads as "this client has no documents".
  return null
}

/**
 * The composer, and the three things it refuses to do.
 *
 * **It does not keep your text in React state.** Spec 6.1: the draft is a row, written
 * before Gmail is ever called, and it is written *while you type*. A composer that held
 * the text in memory would lose it to a refresh, a closed tab or an HTTP error, and
 * losing a hand-written email to a client is not a defect somebody shrugs at.
 *
 * **It never says «inviata» about a message nobody knows the fate of.** `incerto` is a
 * real state with its own words: Gmail did not answer, so the message may or may not be
 * in the client's inbox. The composer offers «Verifica» -- which asks Gmail -- and offers
 * no Send button at all. There is deliberately no "riprova" here: the send is the one
 * call in the system with no idempotency key, so a retry is a second email, and an
 * unknown outcome is resolved by asking rather than by sending again.
 *
 * **It offers no file upload.** Attachments come from `document_versions` (spec 6.4), and
 * `AttachmentPicker` is the whole of the control. A file input here would be a second
 * route for bytes into the system, beside the one slice 2 versions and audits.
 *
 * Every failure on this screen is rendered from the mutation's own `error`, never copied
 * into component state. A refused action followed by a successful one, printing success
 * under a red alert still claiming the opposite, is a defect this codebase has already
 * fixed twice (`CostCategoriesPanel`, `RatesPanel`) -- and the stored `last_error` obeys
 * the same rule from the other side: the server clears it when a `fallito` draft is
 * edited back to `bozza`, so the banner disappears because the fact did, not because a
 * component remembered to reset something.
 */
export function EmailComposer({ entityType, entityId, draftId, defaultTo, onClose }: Props) {
  // The id this composer is actually working on. Seeded from the prop and then owned
  // here, because a new draft acquires one mid-session: the create happens on the first
  // save, and everything after it is an update of that row.
  const [activeId, setActiveId] = useState<string | undefined>(draftId)
  const draft = useDraft(activeId)
  const create = useCreateDraft()
  const update = useUpdateDraft()
  const send = useSendDraft()
  const reconcile = useReconcileDraft()

  // Two namespaces even though a draft has no custom fields today: provenance is
  // structural, decided once, so a custom field later has a place to go rather than being
  // merged in at submit. The same split `TemplateFormValues` documents.
  const [form, setForm] = useState({
    native: { to: (defaultTo ?? []).join(', '), cc: '', subject: '', body: '' },
    custom: {} as Record<string, unknown>,
  })
  const seeded = useRef(activeId === undefined)

  // Synchronous, unlike `useState`: a double click dispatches both events before React
  // has re-rendered with `isPending`, so a state flag read from the closure would still
  // be `false` on the second one. This is the guard that actually holds, and the
  // `disabled` prop below is the one the user sees.
  const sendingOnce = useRef(false)
  const [sending, setSending] = useState(false)

  // Seeded once, from the server. Not a controlled mirror of `draft.data`: re-seeding on
  // every refetch would overwrite whatever the person has typed since, and the autosave
  // guarantees a refetch is always in flight.
  useEffect(() => {
    if (seeded.current || !draft.data) return
    seeded.current = true
    setForm({
      native: {
        to: draft.data.to_addresses.join(', '),
        cc: draft.data.cc_addresses.join(', '),
        subject: draft.data.subject,
        body: draft.data.body_markdown,
      },
      custom: {},
    })
  }, [draft.data])

  const state = draft.data?.send_state
  // `undefined` while a new draft has no row yet: nothing has been sent, so it is
  // editable. `isEditable` covers `fallito` too -- spec 6.3(a) reopens a failed draft
  // with the text inside, and editing it returns it to `bozza` with the error cleared.
  const editable = activeId === undefined || isEditable(state)

  const to = parseAddresses(form.native.to)
  const cc = parseAddresses(form.native.cc)
  const worthSaving = to.length > 0 && (form.native.subject !== '' || form.native.body !== '')

  // Saves while you type. Gated on `editable` and not on `state === 'bozza'`: a `fallito`
  // draft is editable by design, and a save gate that excluded it would let somebody
  // correct the very text the error is about and lose the correction -- which is the
  // failure spec 6.3(a) exists to prevent, arrived at from the wrong side.
  useEffect(() => {
    if (!editable || !worthSaving) return
    const timer = setTimeout(() => {
      if (activeId === undefined) {
        create.mutate(
          {
            entity_type: entityType,
            entity_id: entityId,
            to_addresses: to,
            cc_addresses: cc,
            subject: form.native.subject,
            body_markdown: form.native.body,
            // Empty, and it stays empty here: which document to attach is a separate
            // decision, taken in the picker below by somebody who can see what they are
            // attaching. A new draft has nothing to carry yet.
            attachment_version_ids: [],
          },
          { onSuccess: (created) => setActiveId(created.id) },
        )
        return
      }
      update.mutate({
        id: activeId,
        patch: {
          to_addresses: to,
          cc_addresses: cc,
          subject: form.native.subject,
          body_markdown: form.native.body,
        },
      })
    }, AUTOSAVE_MS)
    return () => clearTimeout(timer)
    // `create` and `update` are deliberately absent: React Query's mutation objects are a
    // new identity on every render, so depending on them would restart the timer forever
    // and turn the debounce into a save per render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form, activeId, editable, worthSaving, entityType, entityId])

  // The failure branch before the loading one. On an error `isPending` is false while
  // `data` is still undefined, so a single `isPending || !data` guard would answer a
  // failed read with a spinner that never resolves -- and would render the controls of a
  // draft nobody managed to read. Fixed three times already in this codebase.
  if (activeId !== undefined && draft.isError) return <QueryErrorBanner error={draft.error} />
  if (activeId !== undefined && !draft.data)
    return <p className="text-muted-foreground">Caricamento…</p>

  const heading = state ? STATE_HEADING[state] : 'Bozza'
  const help = state ? STATE_HELP[state] : STATE_HELP.bozza
  const attachments = draft.data?.attachment_version_ids ?? []
  const missingAttachment = promisesAnAttachmentItDoesNotHave({
    body: form.native.body,
    attachmentCount: attachments.length,
  })

  function setNative(key: 'to' | 'cc' | 'subject' | 'body', value: string) {
    setForm((current) => ({ ...current, native: { ...current.native, [key]: value } }))
  }

  return (
    <div role="dialog" aria-label="Scrivi un'email" className="space-y-4">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-medium">{heading}</h2>
          <p className="text-sm text-muted-foreground">{help}</p>
        </div>
        <Button type="button" variant="ghost" onClick={onClose}>
          Chiudi
        </Button>
      </header>

      {/* The server's own sentence about the last attempt. Rendered from the row rather
          than from component state, so it disappears when the fact does. */}
      {draft.data?.last_error ? (
        <p role="status" className="rounded-lg border bg-muted px-3 py-2 text-sm">
          {draft.data.last_error}
        </p>
      ) : null}

      {create.isError && <QueryErrorBanner error={create.error} />}
      {update.isError && <QueryErrorBanner error={update.error} />}
      {send.isError && <QueryErrorBanner error={send.error} />}
      {reconcile.isError && <QueryErrorBanner error={reconcile.error} />}

      <div className="space-y-1">
        <Label htmlFor="composer-to">A</Label>
        <Input
          id="composer-to"
          aria-label="A"
          value={form.native.to}
          disabled={!editable}
          onChange={(event) => setNative('to', event.target.value)}
        />
      </div>

      <div className="space-y-1">
        <Label htmlFor="composer-cc">Cc</Label>
        <Input
          id="composer-cc"
          aria-label="Cc"
          value={form.native.cc}
          disabled={!editable}
          onChange={(event) => setNative('cc', event.target.value)}
        />
      </div>

      <div className="space-y-1">
        <Label htmlFor="composer-subject">Oggetto</Label>
        <Input
          id="composer-subject"
          aria-label="Oggetto"
          value={form.native.subject}
          disabled={!editable}
          onChange={(event) => setNative('subject', event.target.value)}
        />
      </div>

      <div className="space-y-1">
        <Label htmlFor="composer-body">Testo</Label>
        <Textarea
          id="composer-body"
          aria-label="Testo"
          rows={14}
          value={form.native.body}
          disabled={!editable}
          onChange={(event) => setNative('body', event.target.value)}
        />
      </div>

      <AttachmentPicker
        owner={ownerFor(entityType, entityId)}
        selected={attachments}
        disabled={!editable || activeId === undefined}
        onChange={(versionIds) =>
          activeId === undefined
            ? undefined
            : update.mutate({ id: activeId, patch: { attachment_version_ids: versionIds } })
        }
      />

      {missingAttachment && (
        <p
          role="status"
          className="rounded-lg border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-sm"
        >
          Il testo parla di un allegato, ma non ne hai messo nessuno. Chi la riceve lo
          cercherà.
        </p>
      )}

      <footer className="flex gap-2">
        {state === 'incerto' ? (
          <Button
            type="button"
            disabled={reconcile.isPending || activeId === undefined}
            onClick={() => activeId !== undefined && reconcile.mutate(activeId)}
          >
            Verifica
          </Button>
        ) : null}

        {/* No Send while the outcome is unknown, and no "riprova" either. `editable` is
            false for `incerto` and `in_invio`, so this branch is the whole of the rule:
            the only way out of «esito da verificare» is to ask. */}
        {editable ? (
          <Button
            type="button"
            disabled={sending || send.isPending || activeId === undefined || !worthSaving}
            onClick={() => {
              if (sendingOnce.current || activeId === undefined) return
              sendingOnce.current = true
              setSending(true)
              send.mutate(activeId, {
                onSettled: () => {
                  sendingOnce.current = false
                  setSending(false)
                },
              })
            }}
          >
            Invia
          </Button>
        ) : null}
      </footer>
    </div>
  )
}
