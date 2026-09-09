import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { InvoicePdfPreview } from './InvoicePdfPreview'
import type { Invoice } from './queries'
import { fetchWithRefresh } from '@/lib/api'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, fetchWithRefresh: vi.fn() }
})

const ISSUED = {
  id: 'inv-1',
  tipo: 'fattura',
  stato: 'emessa',
  pdf_document_id: 'doc-9',
} as unknown as Invoice
const DRAFT = { id: 'inv-2', tipo: 'fattura', stato: 'bozza', pdf_document_id: null } as unknown as Invoice
const PROFORMA = { id: 'pf-1', tipo: 'proforma', stato: 'confermata', pdf_document_id: null } as unknown as Invoice

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>)
}

beforeEach(() => {
  vi.mocked(fetchWithRefresh).mockReset()
  // jsdom has neither: the browser turns a Blob into a URL its viewer can open.
  URL.createObjectURL = vi.fn(() => 'blob:pdf-1')
  URL.revokeObjectURL = vi.fn()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('InvoicePdfPreview', () => {
  it('fetches the PDF through the authenticated path and shows it in a frame', async () => {
    vi.mocked(fetchWithRefresh).mockResolvedValue(
      // A string body: a jsdom `Blob` inside Node's `Response` has no `.stream()`.
      new Response('%PDF-1.7', { status: 200, headers: { 'Content-Type': 'application/pdf' } }),
    )
    wrap(<InvoicePdfPreview invoice={ISSUED} />)
    const frame = await screen.findByTitle('Anteprima PDF fattura')
    expect(fetchWithRefresh).toHaveBeenCalledWith('/api/invoices/inv-1/pdf')
    expect(frame).toHaveAttribute('src', expect.stringMatching(/^blob:pdf-1#toolbar=0/))
  })

  it('revokes the blob URL when the page leaves', async () => {
    vi.mocked(fetchWithRefresh).mockResolvedValue(
      // A string body: a jsdom `Blob` inside Node's `Response` has no `.stream()`.
      new Response('%PDF-1.7', { status: 200, headers: { 'Content-Type': 'application/pdf' } }),
    )
    const { unmount } = wrap(<InvoicePdfPreview invoice={ISSUED} />)
    await screen.findByTitle('Anteprima PDF fattura')
    unmount()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:pdf-1')
  })

  it('asks the server for nothing when there is no PDF yet, and says why', () => {
    wrap(<InvoicePdfPreview invoice={DRAFT} />)
    expect(fetchWithRefresh).not.toHaveBeenCalled()
    expect(screen.getByText(/si genera all’emissione/)).toBeInTheDocument()
  })

  it('tells a proforma which button produces its PDF', () => {
    wrap(<InvoicePdfPreview invoice={PROFORMA} />)
    expect(screen.getByText(/«PDF proforma» lo produce/)).toBeInTheDocument()
  })

  it('shows the server refusal instead of an empty frame', async () => {
    vi.mocked(fetchWithRefresh).mockResolvedValue(
      new Response(JSON.stringify({ detail: 'invoice_artifact non trovato' }), { status: 404 }),
    )
    wrap(<InvoicePdfPreview invoice={ISSUED} />)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/non trovato/))
    expect(screen.queryByTitle(/Anteprima PDF/)).not.toBeInTheDocument()
  })
})
