import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { EmailTab } from './EmailTab'
import type { GmailMessageRead } from './queries'
import { api } from '@/lib/api'

// `api` is an openapi-fetch client built at import time, so it is mocked as a module
// (the shape GmailPanel.test.tsx established); stubbing `globalThis.fetch` would never
// be seen by it, and `vi.doMock` after this file's own static imports would be applied
// to nothing.
vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { GET: vi.fn() } }
})

function ok(data: unknown) {
  return { data, response: new Response(null, { status: 200 }) } as never
}

function failed(error: unknown, status: number) {
  return { error, response: new Response(null, { status }) } as never
}

const ENTITY_ID = '00000000-0000-7000-8000-000000000001'

/** Deliberately anodyne fixtures. Nothing that looks like real correspondence goes
 *  into a test, because a failing assertion prints the rendered DOM. */
function message(overrides: Partial<GmailMessageRead> = {}): GmailMessageRead {
  return {
    id: 'a',
    gmail_message_id: 'm1',
    gmail_thread_id: 't1',
    direction: 'inbound',
    from_address: 'ada@acme.it',
    to_addresses: ['io@example.it'],
    cc_addresses: [],
    subject: 'Rinnovo',
    snippet: 'Anteprima',
    internal_date: '2026-08-18T10:00:00Z',
    body_text: 'Testo del messaggio.',
    body_truncated: false,
    body_html_scartato: false,
    attachments: [],
    ...overrides,
  }
}

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <EmailTab entityType="customer" entityId={ENTITY_ID} />
    </QueryClientProvider>,
  )
}

/**
 * Routes both reads the tab makes. Two, since B2-11: the stored correspondence and the
 * drafts that have not left. A single `mockResolvedValue` would answer the drafts query
 * with a list of messages -- which happens to survive `?? []` and so would pass while
 * testing nothing about the drafts at all.
 */
function respond(args: { messages?: unknown; drafts?: unknown } = {}) {
  vi.mocked(api.GET).mockImplementation(((path: string) => {
    if (path === '/api/gmail/messages') return Promise.resolve(args.messages ?? ok([]))
    if (path === '/api/email-drafts')
      return Promise.resolve(args.drafts ?? ok({ items: [], total: 0 }))
    throw new Error(`unexpected GET ${path}`)
  }) as never)
}

function messagesCall() {
  return vi.mocked(api.GET).mock.calls.find((call) => call[0] === '/api/gmail/messages')
}

beforeEach(() => {
  vi.mocked(api.GET).mockReset()
})

describe('EmailTab', () => {
  it('asks only for this entity, and only for the stored mirror', async () => {
    respond({ messages: ok([message()]) })
    renderTab()

    expect(await screen.findByText('Rinnovo')).toBeInTheDocument()
    expect(messagesCall()?.[1]).toMatchObject({
      params: { query: { entity_type: 'customer', entity_id: ENTITY_ID } },
    })
    // And nothing on either read is a Gmail search string: both reach the CRM's own rows.
    expect(vi.mocked(api.GET).mock.calls.map((call) => call[0]).sort()).toEqual([
      '/api/email-drafts',
      '/api/gmail/messages',
    ])
  })

  it('groups messages by thread and shows the direction', async () => {
    respond({
      messages: ok([
        message({ id: 'a', gmail_message_id: 'm1' }),
        message({
          id: 'b',
          gmail_message_id: 'm2',
          direction: 'outbound',
          from_address: 'io@example.it',
        }),
        message({ id: 'c', gmail_message_id: 'm3', gmail_thread_id: 't2', subject: 'Altro' }),
      ]),
    })
    renderTab()

    expect(await screen.findByText('Rinnovo')).toBeInTheDocument()
    expect(screen.getAllByRole('group')).toHaveLength(2)
    // Two of the three fixtures are inbound, so this is `getAllByText`: the brief's
    // `getByText` would fail on its own fixture for being ambiguous, not for being
    // wrong about the component.
    expect(screen.getAllByText('Ricevuta')).toHaveLength(2)
    expect(screen.getByText('Inviata')).toBeInTheDocument()
  })

  /**
   * The conversation being worked on is the one that moved last. The order is computed
   * from the messages rather than taken from the response: the API orders by
   * `(gmail_thread_id, internal_date)` -- stable, but by an opaque Gmail id, so the
   * newest exchange would land wherever its thread id happened to sort.
   */
  it('puts the most recently active conversation first', async () => {
    respond({
      messages: ok([
        message({ id: 'a', gmail_thread_id: 't1', subject: 'Vecchia', internal_date: '2026-08-01T10:00:00Z' }),
        message({ id: 'b', gmail_thread_id: 't1', subject: 'Vecchia', internal_date: '2026-08-02T10:00:00Z' }),
        message({ id: 'c', gmail_thread_id: 't2', subject: 'Recente', internal_date: '2026-08-20T10:00:00Z' }),
      ]),
    })
    renderTab()

    await screen.findByText('Recente')
    expect(screen.getAllByRole('group').map((group) => group.getAttribute('aria-label'))).toEqual([
      'Recente',
      'Vecchia',
    ])
  })

  it('offers open in Gmail on every message', async () => {
    respond({ messages: ok([message()]) })
    renderTab()

    expect(await screen.findByRole('link', { name: 'Apri in Gmail' })).toHaveAttribute(
      'href',
      'https://mail.google.com/mail/u/0/#all/m1',
    )
  })

  /**
   * A failed read and an empty mailbox are two different claims, and the second one is
   * a lie when the first is what happened -- the defect `QueryErrorBanner` exists for.
   * The error branch is checked before the loading branch, because on an error
   * `isPending` is false while `data` is still undefined.
   */
  it('never renders an empty list for a failed request', async () => {
    respond({ messages: failed({ detail: 'database non raggiungibile' }, 503) })
    renderTab()

    expect(await screen.findByRole('alert')).toHaveTextContent('database non raggiungibile')
    expect(screen.queryByText(/Nessuna email/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Caricamento/)).not.toBeInTheDocument()
  })

  it('says plainly that there is nothing yet, when there genuinely is not', async () => {
    respond({ messages: ok([]) })
    renderTab()

    expect(await screen.findByText(/Nessuna email/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('marks a message whose body was dropped or truncated, rather than showing a lie', async () => {
    respond({
      messages: ok([message({ body_truncated: true, body_html_scartato: true })]),
    })
    renderTab()

    expect(await screen.findByText(/troncato/)).toBeInTheDocument()
    expect(screen.getByText(/solo HTML/)).toBeInTheDocument()
  })

  /**
   * `gmail_store_bodies` off is a declared degradation, not a missing value: the
   * mailbox owner switched it off and only headers and Gmail's own snippet are kept.
   * Rendering that snippet as though it were the message would be the CRM claiming a
   * two-line email; saying which one it is costs a sentence.
   */
  it('shows the snippet, labelled as such, when no body was archived', async () => {
    vi.mocked(api.GET).mockResolvedValue(ok([message({ body_text: '', snippet: 'Anteprima' })]))
    renderTab()

    expect(await screen.findByText('Anteprima')).toBeInTheDocument()
    expect(screen.getByText(/non è archiviato/)).toBeInTheDocument()
  })

  /**
   * Spec 5.4 stores no attachment bytes, and the endpoint that would fetch them from
   * Gmail and write them through `DocumentService` is not in this slice's REST surface.
   * The attachment is still named -- knowing an invoice was attached is most of the
   * value -- and the action that does not exist yet says so instead of failing.
   */
  it('names an attachment and does not offer an action that has no endpoint', async () => {
    respond({
      messages: ok([
        message({
          attachments: [{ filename: 'preventivo.pdf', mime: 'application/pdf', size: 20480 }],
        }),
      ]),
    })
    renderTab()

    expect(await screen.findByText(/preventivo\.pdf/)).toBeInTheDocument()
    const save = screen.getByRole('button', { name: 'Salva come documento' })
    expect(save).toBeDisabled()
    expect(save).toHaveAttribute('title', 'In arrivo')
  })

  // --- the composer, from the tab that opens it ----------------------------------------

  it('opens the composer from «Scrivi», with the recipient a reply would go to', async () => {
    respond({ messages: ok([message()]) })
    renderTab()

    await userEvent.click(await screen.findByRole('button', { name: 'Scrivi' }))

    expect(screen.getByRole('dialog', { name: "Scrivi un'email" })).toBeInTheDocument()
    // Read off the correspondence already on screen: the counterpart of the newest
    // message, which for one we received is whoever sent it.
    expect(screen.getByLabelText('A')).toHaveValue('ada@acme.it')
  })

  /**
   * A draft that has not left is not part of the conversation the client has seen.
   * Putting it inside the thread would show a message that never went -- «il CRM crede
   * una cosa diversa da quella che è successa», in the one place a person looks to find
   * out what was said.
   */
  it('lists unsent drafts above the correspondence, with their state in words', async () => {
    respond({
      messages: ok([message()]),
      drafts: ok({
        items: [
          {
            id: 'd1',
            entity_type: 'customer',
            entity_id: ENTITY_ID,
            google_account_id: null,
            to_addresses: ['ada@acme.it'],
            cc_addresses: [],
            subject: 'Preventivo rivisto',
            body_markdown: 'Testo',
            attachment_version_ids: [],
            message_id_header: '<a.1@crm.example.it>',
            in_reply_to_message_id: null,
            send_state: 'incerto',
            send_attempted_at: null,
            last_error: null,
            sent_gmail_message_id: null,
            payment_reminder_id: null,
            created_at: '2026-08-20T09:00:00Z',
            updated_at: '2026-08-20T09:00:00Z',
          },
        ],
        total: 1,
      }),
    })
    renderTab()

    expect(await screen.findByText('Preventivo rivisto')).toBeInTheDocument()
    // The state is words, not a colour: «esito da verificare» is the whole point of the
    // row, and it must never read as «inviata».
    expect(screen.getByText('Esito da verificare')).toBeInTheDocument()
  })

  it('keeps showing the correspondence when the drafts read fails', async () => {
    // Two reads, two claims. A drafts query that failed must not take down the thread
    // the person actually came for.
    respond({
      messages: ok([message()]),
      drafts: failed({ detail: 'bozze non raggiungibili' }, 503),
    })
    renderTab()

    expect(await screen.findByText('Rinnovo')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('bozze non raggiungibili')
  })
})
