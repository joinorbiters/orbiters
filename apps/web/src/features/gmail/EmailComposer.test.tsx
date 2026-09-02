import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { EmailComposer } from './EmailComposer'
import type { EmailDraftRead } from './draftQueries'
import { api } from '@/lib/api'

// `api` is an openapi-fetch client built at import time, so it is mocked as a module --
// the shape `GmailPanel.test.tsx` established. Stubbing `globalThis.fetch` would never be
// seen by it, and `vi.doMock` after this file's own static imports would apply to
// nothing. The hooks under test are the real ones: what is faked is the wire.
vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: { GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() },
  }
})

function ok(data: unknown) {
  return { data, response: new Response(null, { status: 200 }) } as never
}

function failed(error: unknown, status: number) {
  return { error, response: new Response(null, { status }) } as never
}

const ENTITY_ID = '00000000-0000-7000-8000-000000000001'
const DRAFT_ID = '00000000-0000-7000-8000-0000000000d1'
const VERSION_ID = '00000000-0000-7000-8000-0000000000v1'.replace('v', 'a')

/** Deliberately anodyne. A failing assertion prints the rendered DOM, so nothing that
 *  looks like real correspondence goes into a fixture. */
function draft(overrides: Partial<EmailDraftRead> = {}): EmailDraftRead {
  return {
    id: DRAFT_ID,
    entity_type: 'customer',
    entity_id: ENTITY_ID,
    google_account_id: null,
    to_addresses: ['ada@acme.it'],
    cc_addresses: [],
    subject: 'Offerta',
    body_markdown: 'Gentile Ada,',
    attachment_version_ids: [],
    message_id_header: '<a.1@crm.example.it>',
    in_reply_to_message_id: null,
    send_state: 'bozza',
    send_attempted_at: null,
    last_error: null,
    sent_gmail_message_id: null,
    payment_reminder_id: null,
    created_at: '2026-08-20T09:00:00Z',
    updated_at: '2026-08-20T09:00:00Z',
    ...overrides,
  }
}

const DOCUMENT = {
  id: '00000000-0000-7000-8000-0000000000c1',
  customer_id: ENTITY_ID,
  deal_id: null,
  tipo: 'offerta',
  titolo: 'Offerta Acme',
  stato: 'bozza',
  versione_corrente: 1,
  custom_fields: {},
  created_at: '2026-08-20T09:00:00Z',
  updated_at: '2026-08-20T09:00:00Z',
  deleted_at: null,
}

const VERSION = {
  id: VERSION_ID,
  document_id: DOCUMENT.id,
  numero: 1,
  template_id: null,
  storage_key: 'documents/x.pdf',
  content_type: 'application/pdf',
  dimensione: 1024,
  hash_sha256: '0'.repeat(64),
  creato_da: null,
  created_at: '2026-08-20T09:00:00Z',
}

/** Routes every GET the composer makes. The draft is the interesting one; the two
 *  document reads exist so the attachment picker is exercised rather than stubbed away. */
function respondTo(current: EmailDraftRead | { error: unknown; status: number }) {
  vi.mocked(api.GET).mockImplementation((path: string) => {
    if (path === '/api/email-drafts/{draft_id}') {
      return Promise.resolve(
        'error' in current ? failed(current.error, current.status) : ok(current),
      )
    }
    if (path === '/api/documents') return Promise.resolve(ok({ items: [DOCUMENT], total: 1 }))
    if (path === '/api/documents/{document_id}/versions') return Promise.resolve(ok([VERSION]))
    throw new Error(`unexpected GET ${path}`)
  })
}

function renderComposer(props: Partial<Parameters<typeof EmailComposer>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onClose = vi.fn()
  render(
    <QueryClientProvider client={client}>
      <EmailComposer
        entityType="customer"
        entityId={ENTITY_ID}
        draftId={DRAFT_ID}
        onClose={onClose}
        {...props}
      />
    </QueryClientProvider>,
  )
  return { onClose }
}

beforeEach(() => {
  vi.mocked(api.GET).mockReset()
  vi.mocked(api.POST).mockReset()
  vi.mocked(api.PATCH).mockReset()
  vi.mocked(api.DELETE).mockReset()
})

describe('EmailComposer', () => {
  it('opens with the draft that is already on the row', async () => {
    respondTo(draft())
    renderComposer()

    expect(await screen.findByLabelText('A')).toHaveValue('ada@acme.it')
    expect(screen.getByLabelText('Oggetto')).toHaveValue('Offerta')
    expect(screen.getByLabelText('Testo')).toHaveValue('Gentile Ada,')
  })

  it('saves while you type, so a refresh does not lose the text', async () => {
    // Spec 6.1. A composer that keeps the text only in React state loses it on the first
    // refresh, and losing a hand-written email to a client is not a defect anybody shrugs
    // at. The row is the durable thing; this is what keeps it current.
    respondTo(draft())
    vi.mocked(api.PATCH).mockResolvedValue(ok(draft({ body_markdown: 'Gentile Ada, buongiorno' })))
    renderComposer()

    await userEvent.type(await screen.findByLabelText('Testo'), ' buongiorno')

    await waitFor(
      () => {
        expect(api.PATCH).toHaveBeenCalledWith(
          '/api/email-drafts/{draft_id}',
          expect.objectContaining({
            body: expect.objectContaining({ body_markdown: 'Gentile Ada, buongiorno' }),
          }),
        )
      },
      { timeout: 3000 },
    )
  })

  it('keeps saving a failed draft, because a failed draft is still editable', async () => {
    // Spec 6.3(a): the composer reopens with the text inside, and editing returns the row
    // to `bozza`. A save gate that only fired on `bozza` would let somebody correct the
    // very text the error is about and then lose the correction -- the same loss the
    // `email_drafts` table exists to prevent, arrived at from the wrong side.
    respondTo(draft({ send_state: 'fallito', last_error: 'Gmail ha rifiutato il messaggio.' }))
    vi.mocked(api.PATCH).mockResolvedValue(ok(draft()))
    renderComposer()

    await userEvent.type(await screen.findByLabelText('Testo'), ' corretto')

    await waitFor(() => expect(api.PATCH).toHaveBeenCalled(), { timeout: 3000 })
  })

  it('shows an uncertain outcome as «esito da verificare» and never as «inviata»', async () => {
    // Spec 6.3(b). `incerto` means nobody knows whether the message left. Saying "sent"
    // about it is the exact lie this design exists to prevent, and it is what makes
    // somebody send a second copy of an email their client already has.
    respondTo(
      draft({
        send_state: 'incerto',
        last_error: 'Non sappiamo se il messaggio sia partito: Gmail non ha risposto.',
      }),
    )
    renderComposer()

    expect(await screen.findByText('Esito da verificare')).toBeInTheDocument()
    expect(screen.queryByText(/inviata/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Verifica' })).toBeInTheDocument()
  })

  it('offers no Send, and no retry, for a draft whose outcome is unknown', async () => {
    // The send has no idempotency key, so "riprova" would be a second email. The only way
    // out of this state is to ask Gmail what happened.
    respondTo(draft({ send_state: 'incerto' }))
    renderComposer()

    await screen.findByText('Esito da verificare')
    expect(screen.queryByRole('button', { name: 'Invia' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /riprova/i })).not.toBeInTheDocument()
    expect(api.POST).not.toHaveBeenCalled()
  })

  it('verifies by asking Gmail, and never by posting the send again', async () => {
    respondTo(draft({ send_state: 'incerto' }))
    vi.mocked(api.POST).mockResolvedValue(ok(draft({ send_state: 'inviato' })))
    renderComposer()

    await userEvent.click(await screen.findByRole('button', { name: 'Verifica' }))

    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1))
    expect(api.POST).toHaveBeenCalledWith(
      '/api/email-drafts/{draft_id}/reconcile',
      expect.anything(),
    )
  })

  it('reopens a failed draft with the text intact and the error beside it', async () => {
    respondTo(
      draft({
        send_state: 'fallito',
        last_error: 'Gmail ha rifiutato il messaggio: la bozza è intatta, correggila.',
      }),
    )
    renderComposer()

    expect(await screen.findByLabelText('Testo')).toHaveValue('Gentile Ada,')
    expect(screen.getByRole('status')).toHaveTextContent('Gmail ha rifiutato il messaggio')
    expect(screen.getByRole('button', { name: 'Invia' })).toBeEnabled()
  })

  it('sends once and only once, so a double click cannot spend twice', async () => {
    respondTo(draft())
    // Never settles: a double click has to be refused by the composer itself, not by the
    // mutation happening to still be in flight when the second event arrives.
    vi.mocked(api.POST).mockReturnValue(new Promise(() => {}) as never)
    renderComposer()

    await userEvent.dblClick(await screen.findByRole('button', { name: 'Invia' }))

    expect(api.POST).toHaveBeenCalledTimes(1)
    expect(api.POST).toHaveBeenCalledWith('/api/email-drafts/{draft_id}/send', expect.anything())
  })

  it('offers no free-form file upload', async () => {
    // Spec 6.4: attachments come from documents only. A file input here would be a second
    // route for bytes into the system, beside the one slice 2 versions, hashes and audits.
    respondTo(draft())
    const { container } = render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <EmailComposer
          entityType="customer"
          entityId={ENTITY_ID}
          draftId={DRAFT_ID}
          onClose={vi.fn()}
        />
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('button', { name: 'Allega un documento' })).toBeInTheDocument()
    expect(container.querySelector('input[type="file"]')).toBeNull()
  })

  it('attaches a document version, never a document', async () => {
    // A document changes. Attaching "the offer" and sending it a week later would send
    // whatever the offer had become, while the client reads the email as the version that
    // was described to them.
    respondTo(draft())
    vi.mocked(api.PATCH).mockResolvedValue(ok(draft({ attachment_version_ids: [VERSION_ID] })))
    renderComposer()

    await userEvent.click(await screen.findByRole('button', { name: 'Allega un documento' }))
    await userEvent.click(await screen.findByRole('button', { name: /Offerta Acme \(v1\)/ }))

    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledWith(
        '/api/email-drafts/{draft_id}',
        expect.objectContaining({ body: { attachment_version_ids: [VERSION_ID] } }),
      ),
    )
  })

  it('warns when the text promises an attachment that is not there', async () => {
    // The half of B2-9's residual that only the composer can catch. `SollecitiService` no
    // longer writes the promise when there is nothing to attach, but nothing stops a
    // person removing the attachment afterwards, or writing «in allegato l'offerta» by
    // hand. A warning and not a refusal: the text is theirs, and «in allegato alla mia
    // precedente email» is a perfectly good sentence.
    respondTo(draft({ body_markdown: 'Gentile Ada,\n\nin allegato trova l’offerta.' }))
    renderComposer()

    await screen.findByLabelText('Testo')
    expect(screen.getByText(/non ne hai messo nessuno/)).toBeInTheDocument()
    // And it does not block the send: the person decides about their own words.
    expect(screen.getByRole('button', { name: 'Invia' })).toBeEnabled()
  })

  it('says nothing about attachments when one is actually attached', async () => {
    respondTo(
      draft({
        body_markdown: 'Gentile Ada,\n\nin allegato trova l’offerta.',
        attachment_version_ids: [VERSION_ID],
      }),
    )
    renderComposer()

    await screen.findByLabelText('Testo')
    expect(screen.queryByText(/non ne hai messo nessuno/)).not.toBeInTheDocument()
  })

  it('answers a failed read with an error and renders no controls under it', async () => {
    // The error branch is checked before the loading one: on an error `isPending` is false
    // while `data` is still undefined, so a single `isPending || !data` guard answers a
    // failed read with a spinner that never resolves. Fixed three times in this codebase
    // already -- and here it would also mean offering Invia for a draft nobody could read.
    respondTo({ error: { detail: 'Bozza non trovata', code: 'not_found' }, status: 404 })
    renderComposer()

    expect(await screen.findByRole('alert')).toHaveTextContent('Bozza non trovata')
    expect(screen.queryByRole('button', { name: 'Invia' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Testo')).not.toBeInTheDocument()
    expect(screen.queryByText('Caricamento…')).not.toBeInTheDocument()
  })

  it('creates nothing when the composer is opened and closed without typing', async () => {
    // A new draft's row is written on the first save, not on open. Otherwise every
    // accidental click on «Scrivi» would leave an empty draft in somebody's list.
    respondTo(draft())
    const { onClose } = renderComposer({ draftId: undefined })

    await userEvent.click(screen.getByRole('button', { name: 'Chiudi' }))

    expect(onClose).toHaveBeenCalled()
    expect(api.POST).not.toHaveBeenCalled()
  })

  it('creates the row on the first save of a new draft, and updates it after that', async () => {
    respondTo(draft())
    vi.mocked(api.POST).mockResolvedValue(ok(draft()))
    vi.mocked(api.PATCH).mockResolvedValue(ok(draft()))
    renderComposer({ draftId: undefined, defaultTo: ['ada@acme.it'] })

    await userEvent.type(screen.getByLabelText('Oggetto'), 'Offerta')

    await waitFor(
      () =>
        expect(api.POST).toHaveBeenCalledWith(
          '/api/email-drafts',
          expect.objectContaining({
            body: expect.objectContaining({
              entity_type: 'customer',
              entity_id: ENTITY_ID,
              to_addresses: ['ada@acme.it'],
            }),
          }),
        ),
      { timeout: 3000 },
    )
    expect(api.POST).toHaveBeenCalledTimes(1)
  })
})
