import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Comment } from '@/lib/api'
import { Comments } from './Comments'

const THREAD: Comment[] = [
  {
    id: 'c2',
    entity_type: 'freelancer',
    entity_id: 'f1',
    testo: 'Ha mandato il portfolio.',
    autore: 'MCP',
    created_at: '2026-09-09T15:30:00Z',
  },
  {
    id: 'c1',
    entity_type: 'freelancer',
    entity_id: 'f1',
    testo: 'Sentito al telefono.\nRichiamare lunedì.',
    autore: 'Ivan',
    created_at: '2026-09-08T09:05:00Z',
  },
]

/** The detail page's part of the contract: it holds the thread and prepends what the
 *  component reports as added, the way the page's query cache does. */
function Harness({ initial }: { initial: Comment[] }) {
  const [comments, setComments] = useState(initial)
  return (
    <Comments
      kind="freelancers"
      id="f1"
      comments={comments}
      onAdded={(created) => setComments((current) => [created, ...current])}
    />
  )
}

function mount(initial: Comment[]) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <Harness initial={initial} />
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('Comments', () => {
  it('renders the thread as given, newest first, with author, date and multi-line text', () => {
    mount(THREAD)
    const section = screen.getByRole('region', { name: 'Commenti' })
    const items = within(section).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('MCP')
    expect(items[0]).toHaveTextContent('Ha mandato il portfolio.')
    expect(items[0]).toHaveTextContent(/9 set 2026/)
    expect(items[1]).toHaveTextContent('Ivan')
    expect(within(items[1]!).getByText(/Richiamare lunedì/)).toHaveClass('whitespace-pre-wrap')
  })

  it('says so when there is nothing yet', () => {
    mount([])
    expect(screen.getByText('Nessun commento, per ora.')).toBeInTheDocument()
  })

  it('posts the text to the entity route, clears the box and shows the new comment on top', async () => {
    const user = userEvent.setup()
    const created: Comment = {
      id: 'c3',
      entity_type: 'freelancer',
      entity_id: 'f1',
      testo: 'Richiamato: parte a ottobre.',
      autore: 'Ivan',
      created_at: '2026-09-10T10:00:00Z',
    }
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify(created), { status: 201 }))
    mount(THREAD)

    const box = screen.getByLabelText('Nuovo commento')
    const button = screen.getByRole('button', { name: 'Aggiungi commento' })
    expect(button).toBeDisabled()
    await user.type(box, '  Richiamato: parte a ottobre.  ')
    expect(button).toBeEnabled()
    await user.click(button)

    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(3))
    expect(screen.getAllByRole('listitem')[0]).toHaveTextContent('Richiamato: parte a ottobre.')
    expect(box).toHaveValue('')

    const [url, init] = fetchSpy.mock.calls[0]!
    expect(url).toBe('/api/hub/freelancers/f1/comments')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(String(init?.body))).toEqual({ testo: 'Richiamato: parte a ottobre.' })
  })

  it('keeps the draft and shows the sentence when the API refuses', async () => {
    const user = userEvent.setup()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: [{ loc: ['body', 'testo'], msg: 'un commento può avere al massimo 4000 caratteri' }],
        }),
        { status: 422 },
      ),
    )
    mount([])
    await user.type(screen.getByLabelText('Nuovo commento'), 'troppo lungo')
    await user.click(screen.getByRole('button', { name: 'Aggiungi commento' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/al massimo 4000/)
    expect(screen.getByLabelText('Nuovo commento')).toHaveValue('troppo lungo')
  })
})
