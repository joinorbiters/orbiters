import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FieldsPanel } from './FieldsPanel'
import { api } from '@/lib/api'

// Keeps the real `unwrap`/`toProblem`/`fieldErrorFrom` (lib/api.ts) so this test
// exercises exactly what production code runs -- only `api.GET/POST/DELETE/PATCH`
// themselves are replaced, the same split `features/deals/queries.test.tsx`
// already uses via `vi.spyOn`. A blanket `unwrap: vi.fn().mockResolvedValue(...)`
// (the brief's own `TokensPanel.test.tsx` sample) cannot express an error
// response at all, which is exactly the shape this file needs to prove: a failed
// list looks like a failure, not an empty result (gap noted in the task brief),
// and a validation error attaches to the right control.
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

const ACTIVE_FIELD = {
  id: 'f1',
  entity_type: 'customer',
  key: 'segmento',
  label: 'Segmento',
  field_type: 'text',
  options: [],
  required: false,
  position: 0,
  archived: false,
}

const ARCHIVED_FIELD = {
  id: 'f2',
  entity_type: 'customer',
  key: 'vecchio_campo',
  label: 'Vecchio campo',
  field_type: 'text',
  options: [],
  required: false,
  position: 1,
  archived: true,
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <FieldsPanel />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(api.GET).mockReset()
  vi.mocked(api.POST).mockReset()
  vi.mocked(toast.error).mockReset()
  vi.mocked(toast.success).mockReset()
})

describe('FieldsPanel', () => {
  it('asks for both active and archived fields, never just the active half', async () => {
    vi.mocked(api.GET).mockReturnValueOnce(Promise.resolve(ok([ACTIVE_FIELD])))
    renderPanel()
    await waitFor(() => expect(api.GET).toHaveBeenCalled())
    expect(api.GET).toHaveBeenCalledWith(
      '/api/field-definitions',
      expect.objectContaining({
        params: { query: { entity_type: 'customer', include_archived: true } },
      }),
    )
  })

  /**
   * The core of the brief's third gap: archiving is reversible by design (the
   * stored JSONB values are never touched -- `FieldDefinitionService.unarchive`'s
   * own docstring), so a screen that only shows active fields and only offers
   * "Archivia" would make that reversibility invisible. This proves an archived
   * field is not merely fetched but actually shown, distinguishably, with a way
   * back.
   */
  it('shows an archived field with a visible status and a way to restore it, not just the active ones', async () => {
    vi.mocked(api.GET).mockReturnValueOnce(Promise.resolve(ok([ACTIVE_FIELD, ARCHIVED_FIELD])))
    renderPanel()

    expect(await screen.findByText('Vecchio campo')).toBeInTheDocument()
    expect(screen.getByText('Archiviato')).toBeInTheDocument()
    expect(screen.getByText('Attivo')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /ripristina vecchio campo/i })).toBeInTheDocument()
  })

  it('unarchives a field through the real endpoint when "Ripristina" is clicked', async () => {
    vi.mocked(api.GET).mockReturnValue(Promise.resolve(ok([ARCHIVED_FIELD])))
    vi.mocked(api.POST).mockReturnValueOnce(
      Promise.resolve(ok({ ...ARCHIVED_FIELD, archived: false })),
    )
    renderPanel()

    const restoreButton = await screen.findByRole('button', { name: /ripristina vecchio campo/i })
    await userEvent.click(restoreButton)

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith(
        '/api/field-definitions/{field_id}/unarchive',
        expect.objectContaining({ params: { path: { field_id: 'f2' } } }),
      ),
    )
  })

  /**
   * The brief's own FieldsPanel had no loading/error handling on this list at
   * all -- a raw `<Table>` mapping straight over `fields.data`. Checked against
   * this task's own instruction to use `QueryErrorBanner` on every list: a
   * failed fetch must not render as an honestly-empty table.
   */
  it('shows a failed list as a distinct alert, not an empty-looking table', async () => {
    // openapi-fetch never rejects for an HTTP error status -- it *resolves* with
    // `{error, response}` (see `lib/api.ts`'s own `unwrap` docstring on why that
    // shape, not a thrown rejection, is the only thing that carries the real
    // status through to `toProblem`). A `Promise.reject` here would exercise
    // `unwrap`'s *network-failure* branch instead of the one this test is for.
    vi.mocked(api.GET).mockReturnValueOnce(
      Promise.resolve(failed({ code: 'http_error', detail: 'Il server non risponde.' }, 503)),
    )
    renderPanel()

    expect(await screen.findByRole('alert')).toHaveTextContent('Il server non risponde.')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('does not gate "Crea" on the label/key being filled in -- the backend decides, not the client', async () => {
    vi.mocked(api.GET).mockReturnValue(Promise.resolve(ok([])))
    renderPanel()

    await userEvent.click(await screen.findByRole('button', { name: /nuovo campo/i }))
    const createButton = screen.getByRole('button', { name: 'Crea' })
    expect(createButton).not.toBeDisabled()
  })

  /**
   * `options` is the one field on this dialog that is only ever rendered
   * conditionally (`NEEDS_OPTIONS.has(fieldType)`) -- proving the message lands
   * *under the Opzioni control*, not merely somewhere on screen, is what
   * distinguishes a correct fix from one that only happens to work when the
   * banner and the field message would look identical anyway.
   */
  it('attaches a validation error from the server to the field it names', async () => {
    vi.mocked(api.GET).mockReturnValue(Promise.resolve(ok([])))
    vi.mocked(api.POST).mockReturnValueOnce(
      Promise.resolve(
        failed(
          {
            code: 'validation_failed',
            detail: 'un campo di tipo select richiede almeno un’opzione',
            field: 'options',
            reason: 'un campo di tipo select richiede almeno un’opzione',
          },
          422,
        ),
      ),
    )
    renderPanel()

    await userEvent.click(await screen.findByRole('button', { name: /nuovo campo/i }))
    const dialog = screen.getByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('Etichetta'), 'Settore')
    await userEvent.click(within(dialog).getByRole('combobox', { name: /tipo/i }))
    await userEvent.click(screen.getByRole('option', { name: 'Selezione singola' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Crea' }))

    const message = await screen.findByText(/richiede almeno un.opzione/)
    expect(within(dialog).getByLabelText('Opzioni (una per riga)')).toBeInTheDocument()
    expect(message.closest('div')).toContainElement(
      within(dialog).getByLabelText('Opzioni (una per riga)'),
    )
  })
})
