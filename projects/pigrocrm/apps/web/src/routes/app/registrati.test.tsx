/**
 * The signup card, driven the way a person drives it. The API client is stubbed at
 * `api.GET`/`api.POST` -- the same seam every other route test in this tree uses --
 * and the router is faked because the page only ever calls `navigate`.
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

beforeEach(() => {
  GET.mockReset()
  POST.mockReset()
  navigate.mockReset()
  GET.mockResolvedValue({ data: { slug: 'ada-lovelace', disponibile: true } })
})

describe('the signup page', () => {
  it('proposes the address from the name and shows it as a URL once the server says it is free', async () => {
    const user = userEvent.setup()
    render(<SignupPage />)
    await user.type(screen.getByLabelText('Il tuo nome'), 'Ada Lovelace')
    expect(screen.getByLabelText('Indirizzo dello spazio')).toHaveValue('ada-lovelace')
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(/\/ada-lovelace è libero/),
    )
    expect(GET).toHaveBeenCalledWith('/api/tenants/{slug}/disponibile', {
      params: { path: { slug: 'ada-lovelace' } },
    })
  })

  it('refuses a reserved or malformed address before asking the server', async () => {
    const user = userEvent.setup()
    render(<SignupPage />)
    const slug = screen.getByLabelText('Indirizzo dello spazio')
    await user.type(slug, 'app')
    expect(screen.getByRole('status')).toHaveTextContent(/riservato/)
    expect(slug).toHaveAttribute('aria-invalid', 'true')
    expect(GET).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Crea lo spazio' })).toBeDisabled()
  })

  it('shows the server reason when the name is taken', async () => {
    GET.mockResolvedValue({
      data: { slug: 'studio', disponibile: false, motivo: 'questo nome è già in uso' },
    })
    const user = userEvent.setup()
    render(<SignupPage />)
    await user.type(screen.getByLabelText('Indirizzo dello spazio'), 'studio')
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/già in uso/))
  })

  it('creates the space and offers the way into it', async () => {
    POST.mockResolvedValue({ data: { slug: 'ada-lovelace' } })
    const user = userEvent.setup()
    render(<SignupPage />)
    await user.type(screen.getByLabelText('Il tuo nome'), 'Ada Lovelace')
    await user.type(screen.getByLabelText('Email'), 'ada@studio.it')
    await user.type(screen.getByLabelText('Password'), 'lunghissima1')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Crea lo spazio' })).toBeEnabled(),
    )
    await user.click(screen.getByRole('button', { name: 'Crea lo spazio' }))
    expect(POST).toHaveBeenCalledWith('/api/tenants/', {
      body: {
        slug: 'ada-lovelace',
        nome: 'Ada Lovelace',
        email: 'ada@studio.it',
        password: 'lunghissima1',
      },
    })
    await waitFor(() => expect(screen.getByText('Il tuo spazio è pronto')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Vai al login del tuo spazio' })).toBeInTheDocument()
  })

  it('shows the problem the API returned and keeps the form', async () => {
    POST.mockResolvedValue({
      error: {
        type: 'x',
        title: 'Conflitto',
        status: 409,
        detail: 'questo nome è già in uso',
        code: 'conflict',
      },
      response: { status: 409 },
    })
    const user = userEvent.setup()
    render(<SignupPage />)
    await user.type(screen.getByLabelText('Il tuo nome'), 'Ada Lovelace')
    await user.type(screen.getByLabelText('Email'), 'ada@studio.it')
    await user.type(screen.getByLabelText('Password'), 'lunghissima1')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Crea lo spazio' })).toBeEnabled(),
    )
    await user.click(screen.getByRole('button', { name: 'Crea lo spazio' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/già in uso/))
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
  })
})
