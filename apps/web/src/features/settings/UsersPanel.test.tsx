import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { UsersPanel } from './UsersPanel'
import { api } from '@/lib/api'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn(), DELETE: vi.fn(), PATCH: vi.fn() } }
})
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

function ok(data: unknown) {
  return { data, response: new Response(null, { status: 200 }) } as never
}

function failed(error: unknown, status: number) {
  return { error, response: new Response(null, { status }) } as never
}

const ADMIN = {
  id: 'u1',
  email: 'admin@pigro.it',
  nome: 'Ada Admin',
  ruolo: 'admin' as const,
  attivo: true,
  created_at: '2026-08-01T10:00:00Z',
}

const DISABLED_USER = {
  id: 'u2',
  email: 'ex@pigro.it',
  nome: 'Ex Collega',
  ruolo: 'collaboratore' as const,
  attivo: false,
  created_at: '2026-08-01T10:00:00Z',
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <UsersPanel />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(api.GET).mockReset()
  vi.mocked(api.POST).mockReset()
  vi.mocked(api.PATCH).mockReset()
  vi.mocked(toast.error).mockReset()
  vi.mocked(toast.success).mockReset()
})

describe('UsersPanel', () => {
  it('lists users with their role and status', async () => {
    vi.mocked(api.GET).mockReturnValue(Promise.resolve(ok([ADMIN, DISABLED_USER])))
    renderPanel()

    expect(await screen.findByText('Ada Admin')).toBeInTheDocument()
    expect(screen.getByText('Amministratore')).toBeInTheDocument()
    expect(screen.getByText('Disattivato')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Riattiva' })).toBeInTheDocument()
  })

  it('shows a failed list as a distinct alert, not an empty-looking table', async () => {
    vi.mocked(api.GET).mockReturnValue(
      Promise.resolve(failed({ code: 'http_error', detail: 'Il server non risponde.' }, 503)),
    )
    renderPanel()
    expect(await screen.findByRole('alert')).toHaveTextContent('Il server non risponde.')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('toggles a user back on through the real endpoint', async () => {
    vi.mocked(api.GET).mockReturnValue(Promise.resolve(ok([DISABLED_USER])))
    vi.mocked(api.PATCH).mockReturnValueOnce(Promise.resolve(ok({ ...DISABLED_USER, attivo: true })))
    renderPanel()

    await userEvent.click(await screen.findByRole('button', { name: 'Riattiva' }))

    await waitFor(() =>
      expect(api.PATCH).toHaveBeenCalledWith(
        '/api/users/{user_id}',
        expect.objectContaining({
          params: { path: { user_id: 'u2' } },
          body: { attivo: true },
        }),
      ),
    )
  })

  /**
   * `UserCreate.password` requires >= 10 characters server-side
   * (`MIN_PASSWORD_LENGTH`, auth/schemas.py), and the brief's own sample gated
   * "Crea" on that exact number client-side. This project's own convention (see
   * `CustomerForm`/`DealForm`/`PersonForm`: Save is disabled only while the
   * mutation is in flight, never on field content) says the backend's message is
   * what the user sees, attached to the field -- not a client-side rule
   * duplicating it. This proves both halves: the button is never gated, and a
   * too-short password's rejection lands on the password field.
   */
  it('never disables "Crea" on password length, and shows the server’s own rejection on the password field', async () => {
    vi.mocked(api.GET).mockReturnValue(Promise.resolve(ok([])))
    vi.mocked(api.POST).mockReturnValueOnce(
      Promise.resolve(
        failed(
          {
            code: 'validation_failed',
            detail: 'deve avere almeno 10 caratteri',
            field: 'password',
            reason: 'deve avere almeno 10 caratteri',
            expected: '>= 10 caratteri',
          },
          422,
        ),
      ),
    )
    renderPanel()

    await userEvent.click(await screen.findByRole('button', { name: /nuovo utente/i }))
    const createButton = screen.getByRole('button', { name: 'Crea' })
    expect(createButton).not.toBeDisabled()

    await userEvent.type(screen.getByLabelText('Nome'), 'Nuovo Utente')
    await userEvent.type(screen.getByLabelText('Email'), 'nuovo@pigro.it')
    await userEvent.type(screen.getByLabelText('Password'), 'corta')
    await userEvent.click(createButton)

    // Not `/almeno 10 caratteri/` alone -- the dialog's own static help text
    // ("La password deve avere almeno 10 caratteri.") already contains that
    // exact phrase, so asserting on it would pass even if the server's message
    // never rendered at all. "(atteso: ...)" only appears in `fieldErrorFrom`'s
    // own formatting of a validation error that carries `expected`, so it can
    // only come from the field-level message this test exists to prove.
    expect(await screen.findByText(/atteso: >= 10 caratteri/)).toBeInTheDocument()
  })

  it('shows a duplicate-email conflict as a banner, since it names no single field', async () => {
    vi.mocked(api.GET).mockReturnValue(Promise.resolve(ok([])))
    vi.mocked(api.POST).mockReturnValueOnce(
      Promise.resolve(
        failed(
          { code: 'conflict', detail: 'esiste già un utente con questa email', email: 'a@b.it' },
          409,
        ),
      ),
    )
    renderPanel()

    await userEvent.click(await screen.findByRole('button', { name: /nuovo utente/i }))
    await userEvent.click(screen.getByRole('button', { name: 'Crea' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('esiste già un utente con questa email')
  })
})
