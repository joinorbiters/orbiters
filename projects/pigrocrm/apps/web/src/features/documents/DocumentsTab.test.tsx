import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { DocumentsTab } from './DocumentsTab'

const DOCUMENT = {
  id: 'doc-1',
  customer_id: 'c-1',
  deal_id: null,
  tipo: 'offerta',
  titolo: 'Offerta 2026-01',
  stato: 'bozza',
  versione_corrente: 1,
  custom_fields: {},
  created_at: '2026-08-10T09:00:00Z',
  updated_at: '2026-08-10T09:00:00Z',
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

// `api.GET`/`api.POST`/`api.DELETE` are spied on directly, not `globalThis.fetch`:
// `openapi-fetch`'s client captures `fetch: baseFetch = globalThis.fetch` once, as a
// default parameter resolved at `createClient()` time (lib/api.ts's module-level
// `export const api = ...`) -- long before any test's `vi.spyOn(globalThis, 'fetch')`
// runs, so that spy would never be consulted for a request made through `api`.
// Confirmed live (see queries.test.tsx and task-14-report.md). The upload and
// download paths are the one deliberate exception: `useUploadVersion` and
// `downloadDocument()` call `fetch()` directly, fresh, inside the function body --
// not through the shared client -- so a `globalThis.fetch` spy *does* intercept
// those two, and is used for exactly those two tests below.
const mockGet = vi.spyOn(api, 'GET')
const mockPost = vi.spyOn(api, 'POST')
const mockDelete = vi.spyOn(api, 'DELETE')

function ok(data: unknown) {
  return Promise.resolve({ data, response: new Response(null, { status: 200 }) } as never)
}

function failed(error: unknown, status: number) {
  return Promise.resolve({ error, response: new Response(null, { status }) } as never)
}

afterEach(() => {
  mockGet.mockReset()
  mockPost.mockReset()
  mockDelete.mockReset()
})

describe('DocumentsTab', () => {
  it('lists the documents with type, state and version', async () => {
    mockGet.mockReturnValue(ok({ items: [DOCUMENT], next_cursor: null }))
    render(<DocumentsTab owner={{ customerId: 'c-1' }} />, { wrapper })
    expect(await screen.findByText('Offerta 2026-01')).toBeInTheDocument()
    expect(screen.getByText('Offerta')).toBeInTheDocument()
    expect(screen.getByText('Bozza')).toBeInTheDocument()
    expect(screen.getByText('v1')).toBeInTheDocument()
  })

  it('shows an explicit empty state when there really are none', async () => {
    mockGet.mockReturnValue(ok({ items: [], next_cursor: null }))
    render(<DocumentsTab owner={{ customerId: 'c-1' }} />, { wrapper })
    expect(await screen.findByText('Nessun documento.')).toBeInTheDocument()
  })

  it('shows the server error instead of an empty list when the request fails', async () => {
    // A failed request must never look like an empty result.
    mockGet.mockReturnValue(failed({ code: 'http_error', detail: 'Servizio non disponibile' }, 503))
    render(<DocumentsTab owner={{ customerId: 'c-1' }} />, { wrapper })
    expect(await screen.findByRole('alert')).toHaveTextContent('Servizio non disponibile')
    expect(screen.queryByText('Nessun documento.')).not.toBeInTheDocument()
  })

  it('accepts a dropped file and uploads it', async () => {
    mockGet.mockReturnValue(ok({ items: [], next_cursor: null }))
    mockPost.mockReturnValue(ok(DOCUMENT))
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ id: 'v-1', document_id: DOCUMENT.id, numero: 1 }),
        { status: 201, headers: { 'content-type': 'application/json' } },
      ),
    )
    render(<DocumentsTab owner={{ customerId: 'c-1' }} />, { wrapper })
    const dropzone = await screen.findByTestId('upload-dropzone')
    const file = new File([new Uint8Array([37, 80, 68, 70])], 'offerta.pdf', {
      type: 'application/pdf',
    })
    const dataTransfer = { files: [file], items: [], types: ['Files'] }
    fireEvent.drop(dropzone, { dataTransfer })
    await waitFor(() => {
      const posted = fetchSpy.mock.calls.some(
        ([url, init]) =>
          String(url).includes('/versions') && (init as RequestInit | undefined)?.method === 'POST',
      )
      expect(posted).toBe(true)
    })
  })

  it('names the file types it accepts so a refusal is never a surprise', async () => {
    mockGet.mockReturnValue(ok({ items: [], next_cursor: null }))
    render(<DocumentsTab owner={{ customerId: 'c-1' }} />, { wrapper })
    const input = await screen.findByLabelText('Carica un documento')
    expect(input).toHaveAttribute('accept', expect.stringContaining('application/pdf'))
  })

  it('downloads through the API when the download button is pressed', async () => {
    mockGet.mockReturnValue(ok({ items: [DOCUMENT], next_cursor: null }))
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('%PDF', { status: 200 }))
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:x')
    globalThis.URL.revokeObjectURL = vi.fn()
    render(<DocumentsTab owner={{ customerId: 'c-1' }} />, { wrapper })
    await userEvent.click(await screen.findByRole('button', { name: 'Scarica Offerta 2026-01' }))
    await waitFor(() => {
      const called = fetchSpy.mock.calls.some(([url]) => String(url).includes('/download'))
      expect(called).toBe(true)
    })
  })
})
