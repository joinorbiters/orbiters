import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AdminAdmins } from './Admins'

const IVAN = { id: '1', email: 'ivan@orbiters.it', nome: 'Ivan', attivo: true, created_at: '2026-09-10T10:00:00Z' }
const ADA = { id: '2', email: 'ada@orbiters.it', nome: 'Ada', attivo: true, created_at: '2026-09-10T11:00:00Z' }

function answer(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <AdminAdmins />
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('the Amministratori page', () => {
  it('shows the list alone, and the form only inside a dialog the button opens', async () => {
    // ORB-125: Ivan wants the form behind a button, not on the page.
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => answer(200, [IVAN]))
    mount()
    await screen.findByText('ivan@orbiters.it')
    expect(screen.queryByLabelText('Nome')).toBeNull()
    expect(screen.queryByRole('dialog')).toBeNull()

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Nuovo amministratore' }))
    const dialog = await screen.findByRole('dialog', { name: 'Nuovo amministratore' })
    expect(within(dialog).getByLabelText('Nome')).toHaveFocus()
    expect(within(dialog).getByLabelText('Email')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Password')).toBeInTheDocument()

    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    await waitFor(() => expect(screen.getByRole('button', { name: 'Nuovo amministratore' })).toHaveFocus())
  })

  it('keeps a refused creation inside the dialog, on the field the server names', async () => {
    const spy = vi.spyOn(globalThis, 'fetch')
    spy.mockResolvedValueOnce(answer(200, [IVAN]))
    spy.mockResolvedValueOnce(
      answer(422, { detail: [{ loc: ['body', 'email'], msg: 'esiste già un amministratore con questa email' }] }),
    )
    mount()
    await screen.findByText('ivan@orbiters.it')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Nuovo amministratore' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Nome'), 'Ancora')
    await user.type(within(dialog).getByLabelText('Email'), 'ivan@orbiters.it')
    await user.type(within(dialog).getByLabelText('Password'), 'una-password-lunga')
    await user.click(within(dialog).getByRole('button', { name: 'Crea amministratore' }))

    const alert = await within(dialog).findByRole('alert')
    expect(alert).toHaveTextContent('esiste già un amministratore con questa email')
    expect(within(dialog).getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true')
    expect(within(dialog).getByLabelText('Nome')).not.toHaveAttribute('aria-invalid')
    // Still open, the draft still there: the person corrects one field, not three.
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Nome')).toHaveValue('Ancora')

    // «Annulla» closes it, and the next opening carries neither the error nor the draft.
    await user.click(within(dialog).getByRole('button', { name: 'Annulla' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    await user.click(screen.getByRole('button', { name: 'Nuovo amministratore' }))
    const again = await screen.findByRole('dialog')
    expect(within(again).queryByRole('alert')).toBeNull()
    expect(within(again).getByLabelText('Email')).not.toHaveAttribute('aria-invalid')
    expect(within(again).getByLabelText('Nome')).toHaveValue('')
  })

  it('stays open while the request is out, so a late answer lands where it was asked', async () => {
    let settle: (response: Response) => void = () => {}
    const pending = new Promise<Response>((resolve) => (settle = resolve))
    const spy = vi.spyOn(globalThis, 'fetch')
    spy.mockResolvedValueOnce(answer(200, [IVAN]))
    spy.mockReturnValueOnce(pending)
    spy.mockResolvedValueOnce(answer(200, [IVAN, ADA]))
    mount()
    await screen.findByText('ivan@orbiters.it')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Nuovo amministratore' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Nome'), 'Ada')
    await user.type(within(dialog).getByLabelText('Email'), 'ada@orbiters.it')
    await user.type(within(dialog).getByLabelText('Password'), 'una-password-lunga')
    await user.click(within(dialog).getByRole('button', { name: 'Crea amministratore' }))
    expect(await within(dialog).findByRole('button', { name: 'Salvo…' })).toBeDisabled()

    await user.keyboard('{Escape}')
    expect(within(dialog).getByRole('button', { name: 'Annulla' })).toBeDisabled()
    await user.click(within(dialog).getByRole('button', { name: 'Annulla' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    settle(answer(201, ADA))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(screen.getByRole('status')).toHaveTextContent('ada@orbiters.it')
  })

  it('closes on success, refreshes the list and says who was created on the page', async () => {
    const spy = vi.spyOn(globalThis, 'fetch')
    spy.mockResolvedValueOnce(answer(200, [IVAN]))
    spy.mockResolvedValueOnce(answer(201, ADA))
    spy.mockResolvedValueOnce(answer(200, [IVAN, ADA]))
    mount()
    await screen.findByText('ivan@orbiters.it')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Nuovo amministratore' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Nome'), 'Ada')
    await user.type(within(dialog).getByLabelText('Email'), 'ada@orbiters.it')
    await user.type(within(dialog).getByLabelText('Password'), 'una-password-lunga')
    await user.click(within(dialog).getByRole('button', { name: 'Crea amministratore' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(await screen.findByRole('status')).toHaveTextContent('ada@orbiters.it')
    await screen.findByText('ada@orbiters.it', { selector: 'td p' })
    const [, init] = spy.mock.calls[1]!
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init?.body as string)).toEqual({ nome: 'Ada', email: 'ada@orbiters.it', password: 'una-password-lunga' })

    // Opening it again starts from an empty form.
    await user.click(screen.getByRole('button', { name: 'Nuovo amministratore' }))
    expect(within(await screen.findByRole('dialog')).getByLabelText('Nome')).toHaveValue('')
  })

  it('opens a prefilled dialog from the pencil on a row, and saves without a password', async () => {
    // ORB-129: the pencil edits one row; an empty password keeps the old one.
    const spy = vi.spyOn(globalThis, 'fetch')
    spy.mockResolvedValueOnce(answer(200, [IVAN, ADA]))
    spy.mockResolvedValueOnce(answer(200, { ...ADA, nome: 'Ada Lovelace' }))
    spy.mockResolvedValueOnce(answer(200, [IVAN, { ...ADA, nome: 'Ada Lovelace' }]))
    mount()
    await screen.findByText('ada@orbiters.it')
    expect(screen.queryByRole('dialog')).toBeNull()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Modifica Ada' }))
    const dialog = await screen.findByRole('dialog', { name: 'Modifica amministratore' })
    expect(within(dialog).getByLabelText('Nome')).toHaveValue('Ada')
    expect(within(dialog).getByLabelText('Email')).toHaveValue('ada@orbiters.it')
    expect(within(dialog).getByLabelText('Nuova password')).toHaveValue('')
    expect(within(dialog).getByLabelText('Nuova password')).not.toBeRequired()

    // Escape brings focus back to the pencil that opened it, then the edit goes through.
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Modifica Ada' })).toHaveFocus())
    await user.click(screen.getByRole('button', { name: 'Modifica Ada' }))
    await screen.findByRole('dialog', { name: 'Modifica amministratore' })

    const reopened = screen.getByRole('dialog')
    await user.clear(within(reopened).getByLabelText('Nome'))
    await user.type(within(reopened).getByLabelText('Nome'), 'Ada Lovelace')
    await user.click(within(reopened).getByRole('button', { name: 'Salva modifiche' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(screen.getByRole('status')).toHaveTextContent('Amministratore aggiornato: ada@orbiters.it')
    await screen.findByText('Ada Lovelace')
    const [url, init] = spy.mock.calls[1]!
    expect(url).toBe('/api/hub/admins/2')
    expect(init?.method).toBe('PATCH')
    expect(JSON.parse(init?.body as string)).toEqual({ nome: 'Ada Lovelace', email: 'ada@orbiters.it' })

    // The create dialog after an edit is empty again, not Ada's row.
    await user.click(screen.getByRole('button', { name: 'Nuovo amministratore' }))
    const fresh = await screen.findByRole('dialog', { name: 'Nuovo amministratore' })
    expect(within(fresh).getByLabelText('Nome')).toHaveValue('')
    expect(within(fresh).getByLabelText('Password')).toBeRequired()
  })

  it('sends a new password from the pencil, and keeps a refusal on its field', async () => {
    const spy = vi.spyOn(globalThis, 'fetch')
    spy.mockResolvedValueOnce(answer(200, [IVAN, ADA]))
    spy.mockResolvedValueOnce(answer(422, { detail: [{ loc: ['body', 'password'], msg: 'almeno 10 caratteri' }] }))
    spy.mockResolvedValueOnce(answer(200, ADA))
    spy.mockResolvedValueOnce(answer(200, [IVAN, ADA]))
    mount()
    await screen.findByText('ada@orbiters.it')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Modifica Ada' }))
    const dialog = await screen.findByRole('dialog')
    const password = within(dialog).getByLabelText('Nuova password')
    // Ten characters typed, so the browser lets it through and the server has its say.
    await user.type(password, 'dieci-lett')
    await user.click(within(dialog).getByRole('button', { name: 'Salva modifiche' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('almeno 10 caratteri')
    expect(password).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await user.type(password, '-ancora')
    await user.click(within(dialog).getByRole('button', { name: 'Salva modifiche' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    const [, init] = spy.mock.calls[2]!
    expect(JSON.parse(init?.body as string)).toEqual({ nome: 'Ada', email: 'ada@orbiters.it', password: 'dieci-lett-ancora' })
  })
})
