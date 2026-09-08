import { useQueries, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Button } from '@/components/ui/button'
import type { Document, DocumentOwner } from '@/features/documents/queries'
import { api, unwrap } from '@/lib/api'
import { queryKeys } from '@/lib/query'

interface Attachable {
  versionId: string
  label: string
}

/**
 * The attachment control, and the reason there is no `<input type="file">` on this screen.
 *
 * Spec 6.4: what an email carries comes from `document_versions` and never from an
 * upload. A file input here would be a second route for bytes into the system, with a
 * second authorisation to write, next to the one slice 2 already versions, hashes and
 * audits -- and the thing attached to a client's email would be the one artefact in the
 * product with no history behind it.
 *
 * A version id and not a document id, because a document changes: attaching "the offer"
 * and sending it a week later would send whatever the offer had become, while the client
 * reads the email as the version that was described to them. The picker attaches the
 * *current* version at the moment of choosing, and shows which one it was.
 */
export function AttachmentPicker({
  owner,
  selected,
  disabled,
  onChange,
}: {
  owner: DocumentOwner | null
  selected: string[]
  disabled: boolean
  onChange: (versionIds: string[]) => void
}) {
  const [open, setOpen] = useState(false)
  // Spelled out rather than reusing `useDocuments`, for one reason: a person has no
  // owner -- a document belongs to a customer XOR a deal -- and hooks cannot be called
  // conditionally, so the query has to be *disabled* rather than pointed at an empty id.
  // `useDocuments({ customerId: '' })` would issue `GET /api/documents?customer_id=` on
  // every person's composer, which is residuo B1 in a new place.
  const documents = useQuery({
    enabled: owner !== null,
    queryKey: queryKeys.documents(owner ?? {}),
    queryFn: () =>
      unwrap(
        api.GET('/api/documents', {
          params: {
            query:
              owner !== null && 'customerId' in owner
                ? { customer_id: owner.customerId }
                : { deal_id: owner !== null && 'dealId' in owner ? owner.dealId : undefined },
          },
        }),
      ),
  })
  const items: Document[] = owner === null ? [] : (documents.data?.items ?? [])

  // One versions query per document. `useQueries` rather than a loop of `useQuery`,
  // because the number of documents is data and a hook count that varies between renders
  // is the one thing React forbids outright.
  const versionQueries = useQueries({
    queries: items.map((document) => ({
      queryKey: queryKeys.documentVersions(document.id),
      queryFn: () =>
        unwrap(
          api.GET('/api/documents/{document_id}/versions', {
            params: { path: { document_id: document.id } },
          }),
        ),
    })),
  })

  // Two things at once, from one read: which version each document would attach, and what
  // an already-attached id is *called*. Without the second, reopening a saved draft would
  // list its attachments as bare UUIDs -- which tells a person nothing about what their
  // client is about to receive.
  const attachable: Attachable[] = []
  const labels = new Map<string, string>()
  items.forEach((document, index) => {
    const versions = versionQueries[index]?.data ?? []
    for (const version of versions) {
      labels.set(version.id, `${document.titolo} (v${version.numero})`)
      if (version.numero === document.versione_corrente) {
        attachable.push({ versionId: version.id, label: `${document.titolo} (v${version.numero})` })
      }
    }
  })

  function toggle(versionId: string) {
    onChange(
      selected.includes(versionId)
        ? selected.filter((id) => id !== versionId)
        : [...selected, versionId],
    )
  }

  return (
    <section className="space-y-2">
      <h3 className="text-sm font-medium">Allegati</h3>

      {selected.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nessun allegato.</p>
      ) : (
        <ul className="space-y-1">
          {selected.map((versionId) => (
            <li key={versionId} className="flex items-center justify-between gap-2 text-sm">
              {/* The id is the fallback, not the intent: it shows only while the version
                  lists are still loading, or for a version whose document is filed under
                  another scheda -- a reminder attaches the invoice's PDF, which belongs to
                  the customer even when the draft is opened from a deal. */}
              <span>{labels.get(versionId) ?? versionId}</span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={disabled}
                aria-label={`Togli allegato ${labels.get(versionId) ?? versionId}`}
                onClick={() => toggle(versionId)}
              >
                Togli
              </Button>
            </li>
          ))}
        </ul>
      )}

      {owner === null ? (
        <p className="text-sm text-muted-foreground">
          I documenti appartengono a un cliente o a un deal: apri il composer da quella
          scheda per allegarne uno.
        </p>
      ) : (
        <>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled}
            aria-expanded={open}
            onClick={() => setOpen((current) => !current)}
          >
            Allega un documento
          </Button>

          {documents.isError && <QueryErrorBanner error={documents.error} />}

          {open && !documents.isError && (
            <ul className="divide-y rounded-lg border">
              {attachable.map((candidate) => (
                <li key={candidate.versionId}>
                  <button
                    type="button"
                    disabled={disabled}
                    className={
                      'w-full px-3 py-2 text-left text-sm hover:bg-muted disabled:opacity-50'
                    }
                    onClick={() => toggle(candidate.versionId)}
                  >
                    {selected.includes(candidate.versionId) ? '✓ ' : ''}
                    {candidate.label}
                  </button>
                </li>
              ))}
              {attachable.length === 0 && (
                <li className="px-3 py-2 text-sm text-muted-foreground">
                  Nessun documento su questa scheda.
                </li>
              )}
            </ul>
          )}
        </>
      )}
    </section>
  )
}
