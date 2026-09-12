/**
 * The signup wizard (spec 2026-09-12 §6.4), driven the way a person drives it: the
 * email, then the name. The API client is stubbed at `api.GET`/`api.POST`, the same
 * seam every other route test in this tree uses, and the router is faked because the
 * page only ever calls `navigate`.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const navigate = vi.fn()
vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return {
    ...actual,
    useNavigate: () => navigate,
    createFileRoute: () => (options: unknown) => options,
  }
})

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: { GET: vi.fn(), POST: vi.fn() },
  }
})

import { api } from '@/lib/api'
import { SignupPage } from './registrati'

const GET = api.GET as unknown as ReturnType<typeof vi.fn>
const POST = api.POST as unknown as ReturnType<typeof vi.fn>

const NOBODY = { membro: false, nome: null, cognome: null, spazi: 0 }
const MEMBER = { membro: true, nome: 'Ada', cognome: 'Lovelace', spazi: 0 }
const OWNER = { membro: true, nome: 'Ada', cognome: 'Lovelace', spazi: 1 }

/** `POST` answers by path: the member question, the link, the signup. */
function answers(by: Record<string, unknown>) {
  POST.mockImplementation(((path: string) =>
    Promise.resolve({ data: by[path], response: { status: 200 } })) as never)
}

async function throughStepOne(user: ReturnType<typeof userEvent.setup>, email = 'ada@studio.it') {
  await user.type(screen.getByLabelText('Con quale email ti conosciamo?'), email)
  await user.click(screen.getByRole('button', { name: 'Avanti' }))
}

beforeEach(() => {
  GET.mockReset()
  POST.mockReset()
  navigate.mockReset()
  GET.mockResolvedValue({ data: { slug: 'ada-lovelace', disponibile: true } })
})

describe('the signup wizard', () => {
  it('asks the email first and greets a member with the name already written', async () => {
    answers({ '/api/tenants/membro': MEMBER })
    const user = userEvent.setup()
    render(<SignupPage />)
    expect(screen.getByText(/1 di 2/)).toBeInTheDocument()
    await throughStepOne(user)
    expect(POST).toHaveBeenCalledWith('/api/tenants/membro', { body: { email: 'ada@studio.it' } })
    expect(await screen.findByText(/Sei dei nostri: ciao Ada/)).toBeInTheDocument()
    expect(screen.getByLabelText('Come si chiama il tuo spazio?')).toHaveValue('Ada Lovelace')
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(/\/ada-lovelace è libero/),
    )
    expect(GET).toHaveBeenCalledWith('/api/tenants/{slug}/disponibile', {
      params: { path: { slug: 'ada-lovelace' } },
    })
    expect(screen.queryByLabelText('Password')).toBeNull()
  })

  it('lets somebody who is not a member in anyway, with the name to type', async () => {
    answers({ '/api/tenants/membro': NOBODY })
    const user = userEvent.setup()
    render(<SignupPage />)
    await throughStepOne(user, 'bob@studio.it')
    expect(await screen.findByText(/2 di 2/)).toBeInTheDocument()
    expect(screen.getByLabelText('Come si chiama il tuo spazio?')).toHaveValue('')
    expect(screen.getByText(/Non sei ancora nella community/)).toBeInTheDocument()
  })

  it('offers the link by mail to an address that already owns a space, and a way to make another', async () => {
    answers({ '/api/tenants/membro': OWNER, '/api/auth/link': { ok: true } })
    const user = userEvent.setup()
    render(<SignupPage />)
    await throughStepOne(user)
    expect(await screen.findByText('Hai già uno spazio')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Mandami il link per entrare' }))
    await waitFor(() =>
      expect(POST).toHaveBeenCalledWith('/api/auth/link', { body: { email: 'ada@studio.it' } }),
    )
    expect(await screen.findByText(/Controlla la posta/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Vuoi crearne un altro?' }))
    expect(screen.getByLabelText('Come si chiama il tuo spazio?')).toBeInTheDocument()
  })

  it('opens the address only on «cambia» and refuses a reserved one before asking the server', async () => {
    answers({ '/api/tenants/membro': NOBODY })
    const user = userEvent.setup()
    render(<SignupPage />)
    await throughStepOne(user, 'bob@studio.it')
    await user.type(await screen.findByLabelText('Come si chiama il tuo spazio?'), 'Studio Bob')
    expect(screen.queryByLabelText('Indirizzo dello spazio')).toBeNull()
    await user.click(screen.getByRole('button', { name: 'cambia' }))
    const slug = screen.getByLabelText('Indirizzo dello spazio')
    expect(slug).toHaveValue('studio-bob')
    GET.mockClear()
    await user.clear(slug)
    await user.type(slug, 'app')
    expect(screen.getByRole('status')).toHaveTextContent(/riservato/)
    expect(slug).toHaveAttribute('aria-invalid', 'true')
    expect(GET).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Crea lo spazio' })).toBeDisabled()
  })

  it('creates the space without a password and lands inside it', async () => {
    answers({ '/api/tenants/membro': MEMBER, '/api/tenants/': { slug: 'ada-lovelace' } })
    const go = vi.fn()
    const user = userEvent.setup()
    render(<SignupPage go={go} />)
    await throughStepOne(user)
    await screen.findByLabelText('Come si chiama il tuo spazio?')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Crea lo spazio' })).toBeEnabled(),
    )
    await user.click(screen.getByRole('button', { name: 'Crea lo spazio' }))
    await waitFor(() =>
      expect(POST).toHaveBeenCalledWith('/api/tenants/', {
        body: { slug: 'ada-lovelace', nome: 'Ada Lovelace', email: 'ada@studio.it', membro: true },
      }),
    )
    await waitFor(() => expect(go).toHaveBeenCalledWith('/ada-lovelace/app/'))
  })

  it('shows the problem the API returned and stays on the name', async () => {
    POST.mockImplementation(((path: string) =>
      Promise.resolve(
        path === '/api/tenants/'
          ? {
              error: { type: 'x', title: 'Conflitto', status: 409, detail: 'questo nome è già in uso', code: 'conflict' },
              response: { status: 409 },
            }
          : { data: NOBODY, response: { status: 200 } },
      )) as never)
    const user = userEvent.setup()
    render(<SignupPage />)
    await throughStepOne(user, 'bob@studio.it')
    await user.type(await screen.findByLabelText('Come si chiama il tuo spazio?'), 'Ada Lovelace')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Crea lo spazio' })).toBeEnabled(),
    )
    await user.click(screen.getByRole('button', { name: 'Crea lo spazio' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/già in uso/))
    expect(screen.getByLabelText('Come si chiama il tuo spazio?')).toBeInTheDocument()
  })

  it('proposes the name to an owner who wants a second space, and lets everyone change the email', async () => {
    answers({ '/api/tenants/membro': OWNER })
    const user = userEvent.setup()
    render(<SignupPage />)
    await throughStepOne(user)
    await screen.findByText('Hai già uno spazio')
    await user.click(screen.getByRole('button', { name: 'Vuoi crearne un altro?' }))
    expect(screen.getByLabelText('Come si chiama il tuo spazio?')).toHaveValue('Ada Lovelace')
    // «Indietro» goes to the email, never back to the owner card, and forgets the name.
    await user.click(screen.getByRole('button', { name: 'Indietro' }))
    expect(screen.getByLabelText('Con quale email ti conosciamo?')).toHaveValue('ada@studio.it')
    expect(screen.queryByText('Hai già uno spazio')).toBeNull()
    await throughStepOne(user)
    await user.click(await screen.findByRole('button', { name: 'Cambia email' }))
    expect(screen.getByLabelText('Con quale email ti conosciamo?')).toBeInTheDocument()
  })

  it('trims the email before asking about it', async () => {
    answers({ '/api/tenants/membro': NOBODY })
    const user = userEvent.setup()
    render(<SignupPage />)
    await throughStepOne(user, '  bob@studio.it ')
    expect(POST).toHaveBeenCalledWith('/api/tenants/membro', { body: { email: 'bob@studio.it' } })
  })
})
