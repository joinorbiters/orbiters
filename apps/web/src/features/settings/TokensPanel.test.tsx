import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TokensPanel } from './TokensPanel'
import { api } from '@/lib/api'

// Keeps the real `unwrap`/`toProblem` (lib/api.ts), only replacing `api.GET/
// POST/DELETE/PATCH` themselves -- unlike the task brief's own sample (a blanket
// `unwrap: vi.fn().mockResolvedValue(...)`), this lets later tests in this file
// express a create call that actually returns the one-time `CreatedToken.token`,
// and a failed call with a real status, which a fixed `unwrap` mock cannot do.
vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn(), DELETE: vi.fn(), PATCH: vi.fn() } }
})
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))
vi.mock('@/lib/auth', () => ({ useAuth: () => ({ user: { ruolo: 'admin' } }) }))

function ok(data: unknown) {
  return { data, response: new Response(null, { status: 200 }) } as never
}

function failed(error: unknown, status: number) {
  return { error, response: new Response(null, { status }) } as never
}

const EXISTING_TOKEN = {
  id: 't1',
  nome: 'Claude',
  prefix: 'pgc_abc12345',
  last_used_at: null,
  revoked_at: null,
  created_at: '2026-08-06T10:00:00Z',
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <TokensPanel />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(api.GET).mockReset()
  vi.mocked(api.POST).mockReset()
  vi.mocked(api.DELETE).mockReset()
  vi.mocked(toast.error).mockReset()
  vi.mocked(toast.success).mockReset()
  Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } })
})

describe('TokensPanel', () => {
  it('explains what the tokens are for', async () => {
    vi.mocked(api.GET).mockReturnValue(Promise.resolve(ok([])))
    renderPanel()
    expect(await screen.findByText(/MCP/i)).toBeInTheDocument()
  })

  /**
   * The brief's own text already says this once ("un token creato da un
   * amministratore..."); this proves it is not merely a passing remark that
   * could get edited away, but survives as a real assertion tied to the exact
   * fact this task called out: no scope, no expiry, full role inheritance.
   */
  it('states plainly that a token carries its owner’s full role, with no scope and no expiry', async () => {
    vi.mocked(api.GET).mockReturnValue(Promise.resolve(ok([])))
    renderPanel()
    expect(await screen.findByText(/senza scadenza/i)).toBeInTheDocument()
    expect(screen.getByText(/creare altri amministratori/i)).toBeInTheDocument()
  })

  it('shows only the prefix of an existing token, never the full secret', async () => {
    vi.mocked(api.GET).mockReturnValue(Promise.resolve(ok([EXISTING_TOKEN])))
    renderPanel()
    expect(await screen.findByText('pgc_abc12345')).toBeInTheDocument()
  })

  it('offers a way to create a new token', async () => {
    vi.mocked(api.GET).mockReturnValue(Promise.resolve(ok([])))
    renderPanel()
    expect(await screen.findByRole('button', { name: /nuovo token/i })).toBeInTheDocument()
  })

  it('shows a failed list as a distinct alert, not an empty-looking table', async () => {
    vi.mocked(api.GET).mockReturnValue(
      Promise.resolve(failed({ code: 'http_error', detail: 'Il server non risponde.' }, 503)),
    )
    renderPanel()
    expect(await screen.findByRole('alert')).toHaveTextContent('Il server non risponde.')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  describe('creating a token — the one-time reveal', () => {
    async function createToken() {
      vi.mocked(api.GET).mockReturnValue(Promise.resolve(ok([])))
      vi.mocked(api.POST).mockReturnValueOnce(
        Promise.resolve(
          ok({
            id: 't2',
            nome: 'Claude sul portatile',
            prefix: 'pgc_zzzz9999',
            last_used_at: null,
            revoked_at: null,
            created_at: '2026-08-06T10:00:00Z',
            token: 'pgc_the-entire-raw-secret-value',
          }),
        ),
      )
      renderPanel()
      await userEvent.click(await screen.findByRole('button', { name: /nuovo token/i }))
      await userEvent.type(screen.getByLabelText('Nome'), 'Claude sul portatile')
      await userEvent.click(screen.getByRole('button', { name: 'Crea' }))
    }

    it('shows the raw token exactly once, right after creation', async () => {
      await createToken()
      expect(await screen.findByDisplayValue('pgc_the-entire-raw-secret-value')).toBeInTheDocument()
    })

    it('never gates "Crea" on the name being filled in -- the backend decides, not the client', async () => {
      vi.mocked(api.GET).mockReturnValue(Promise.resolve(ok([])))
      renderPanel()
      await userEvent.click(await screen.findByRole('button', { name: /nuovo token/i }))
      expect(screen.getByRole('button', { name: 'Crea' })).not.toBeDisabled()
    })

    it('lets the value be copied to the clipboard', async () => {
      await createToken()
      await screen.findByDisplayValue('pgc_the-entire-raw-secret-value')

      await userEvent.click(screen.getByRole('button', { name: /copia il token/i }))

      expect(navigator.clipboard.writeText).toHaveBeenCalledWith('pgc_the-entire-raw-secret-value')
    })

    /**
     * The exact requirement this task calls out: the plaintext is gone forever
     * once this dialog closes (the server stores only a hash -- `PatService.
     * create`'s own comment), so losing it to a stray Escape press or an
     * outside click would be a silent, unrecoverable data loss with no error to
     * even signal it happened. Both standard Radix dismissal paths are checked
     * here, not just one, since either alone dismisses an ordinary Dialog.
     */
    it('cannot be dismissed with Escape or by clicking outside — only the explicit button closes it', async () => {
      await createToken()
      const secret = await screen.findByDisplayValue('pgc_the-entire-raw-secret-value')

      await userEvent.keyboard('{Escape}')
      expect(screen.getByDisplayValue('pgc_the-entire-raw-secret-value')).toBeInTheDocument()

      // Radix's Dialog sets `pointer-events: none` on `<body>` while open (real
      // scroll-lock behaviour, visible in the rendered DOM), which makes
      // `userEvent.click` refuse to target it at all -- correctly, for a real
      // click, but beside the point here. Radix's own "outside" detection
      // listens for a raw `pointerdown` on `document`, which `fireEvent`
      // dispatches directly without user-event's CSS hit-testing, so this is
      // the one interaction that actually exercises `onPointerDownOutside`.
      fireEvent.pointerDown(document.body)
      expect(screen.getByDisplayValue('pgc_the-entire-raw-secret-value')).toBeInTheDocument()

      await userEvent.click(screen.getByRole('button', { name: /ho (copiato|salvato)/i }))
      await waitFor(() => expect(secret).not.toBeInTheDocument())
    })
  })

  describe('revoking a token', () => {
    it('asks for confirmation before revoking, since it cannot be undone', async () => {
      vi.mocked(api.GET).mockReturnValue(Promise.resolve(ok([EXISTING_TOKEN])))
      vi.spyOn(window, 'confirm').mockReturnValue(false)
      renderPanel()

      await userEvent.click(await screen.findByRole('button', { name: /revoca claude/i }))
      expect(api.DELETE).not.toHaveBeenCalled()
    })

    it('revokes through the real endpoint once confirmed', async () => {
      vi.mocked(api.GET).mockReturnValue(Promise.resolve(ok([EXISTING_TOKEN])))
      vi.mocked(api.DELETE).mockReturnValueOnce(Promise.resolve(ok(undefined)))
      vi.spyOn(window, 'confirm').mockReturnValue(true)
      renderPanel()

      await userEvent.click(await screen.findByRole('button', { name: /revoca claude/i }))

      await waitFor(() =>
        expect(api.DELETE).toHaveBeenCalledWith(
          '/api/tokens/{token_id}',
          expect.objectContaining({ params: { path: { token_id: 't1' } } }),
        ),
      )
      await waitFor(() => expect(toast.success).toHaveBeenCalled())
    })

    it('offers no revoke action for an already-revoked token', async () => {
      vi.mocked(api.GET).mockReturnValue(
        Promise.resolve(ok([{ ...EXISTING_TOKEN, revoked_at: '2026-08-05T00:00:00Z' }])),
      )
      renderPanel()

      expect(await screen.findByText('Revocato')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /revoca claude/i })).not.toBeInTheDocument()
    })
  })
})
