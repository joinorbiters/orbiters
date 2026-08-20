import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { VersionHistory } from './VersionHistory'
import type { DocumentVersion } from './queries'

const VERSIONS: DocumentVersion[] = [
  {
    id: 'v-2',
    document_id: 'doc-1',
    numero: 2,
    template_id: 't-1',
    storage_key: 'acme-0123/doc-1/v2.pdf',
    content_type: 'application/pdf',
    dimensione: 12345,
    hash_sha256: 'a'.repeat(64),
    creato_da: null,
    created_at: '2026-08-10T10:00:00Z',
  },
  {
    id: 'v-1',
    document_id: 'doc-1',
    numero: 1,
    template_id: null,
    storage_key: 'acme-0123/doc-1/v1.pdf',
    content_type: 'application/pdf',
    dimensione: 999,
    hash_sha256: 'b'.repeat(64),
    creato_da: null,
    created_at: '2026-08-09T10:00:00Z',
  },
]

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

// `api.GET`/`api.POST` are spied on directly -- see queries.test.tsx and
// task-14-report.md for why `globalThis.fetch` never intercepts a request made
// through the shared `openapi-fetch` client.
const mockGet = vi.spyOn(api, 'GET')
const mockPost = vi.spyOn(api, 'POST')

afterEach(() => {
  mockGet.mockReset()
  mockPost.mockReset()
})

function ok(data: unknown) {
  return Promise.resolve({ data, response: new Response(null, { status: 200 }) } as never)
}

function failed(error: unknown, status: number) {
  return Promise.resolve({ error, response: new Response(null, { status }) } as never)
}

describe('VersionHistory', () => {
  it('lists every version newest first, with its size', async () => {
    mockGet.mockReturnValue(ok(VERSIONS))
    render(<VersionHistory documentId="doc-1" />, { wrapper })
    const items = await screen.findAllByRole('listitem')
    expect(items[0]).toHaveTextContent('v2')
    expect(items[1]).toHaveTextContent('v1')
    expect(items[0]).toHaveTextContent('12,1 kB')
  })

  it('offers regeneration only for a version that came from a template', async () => {
    mockGet.mockReturnValue(ok(VERSIONS))
    render(<VersionHistory documentId="doc-1" />, { wrapper })
    expect(await screen.findByRole('button', { name: 'Rigenera la versione 2' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Rigenera la versione 1' })).not.toBeInTheDocument()
  })

  it('shows the server error instead of an empty history when the request fails', async () => {
    mockGet.mockReturnValue(failed({ code: 'http_error', detail: 'Non disponibile' }, 503))
    render(<VersionHistory documentId="doc-1" />, { wrapper })
    expect(await screen.findByRole('alert')).toHaveTextContent('Non disponibile')
  })

  it('posts a regeneration for the version it was asked about', async () => {
    mockGet.mockReturnValue(ok(VERSIONS))
    mockPost.mockReturnValue(ok({ ...VERSIONS[0], numero: 3 }))
    render(<VersionHistory documentId="doc-1" />, { wrapper })
    await userEvent.click(await screen.findByRole('button', { name: 'Rigenera la versione 2' }))
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/api/documents/{document_id}/versions/{numero}/regenerate',
        expect.objectContaining({ params: { path: { document_id: 'doc-1', numero: 2 } } }),
      )
    })
  })
})
