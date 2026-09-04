import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { toast } from 'sonner'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { InvoiceActions } from './InvoiceActions'
import { InvoiceStateBadge } from './InvoiceStateBadge'
import type { Invoice } from './queries'
import { api } from '@/lib/api'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn(), PUT: vi.fn(), PATCH: vi.fn() } }
})
vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
}))

function ok(data: unknown) {
  return { data, response: new Response(null, { status: 200 }) } as never
}

function failed(error: unknown, status: number) {
  return { error, response: new Response(null, { status }) } as never
}

const DRAFT = { id: 'inv-1', tipo: 'fattura', stato: 'bozza' } as unknown as Invoice
const ISSUED = { id: 'inv-1', tipo: 'fattura', stato: 'emessa' } as unknown as Invoice

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>)
}

beforeEach(() => {
  vi.mocked(api.POST).mockReset()
  vi.mocked(toast.success).mockReset()
  vi.mocked(toast.warning).mockReset()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('InvoiceActions', () => {
  it('asks before issuing, because the number cannot be taken back', async () => {
    vi.mocked(api.POST).mockResolvedValue(ok(ISSUED))
    wrap(<InvoiceActions invoice={DRAFT} />)

    await userEvent.click(screen.getByRole('button', { name: /emetti/i }))
    expect(window.confirm).toHaveBeenCalled()
  })

  it('does not issue when the confirmation is declined', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    wrap(<InvoiceActions invoice={DRAFT} />)

    await userEvent.click(screen.getByRole('button', { name: /emetti/i }))
    expect(api.POST).not.toHaveBeenCalled()
  })

  it('renders the artefacts after issuing, as a second call', async () => {
    vi.mocked(api.POST).mockResolvedValue(ok(ISSUED))
    wrap(<InvoiceActions invoice={DRAFT} />)

    await userEvent.click(screen.getByRole('button', { name: /emetti/i }))
    await waitFor(() => expect(vi.mocked(api.POST).mock.calls.length).toBe(2))
    // The mocked signature widens to `never`, so the tuple is read positionally
    // rather than destructured.
    const paths = vi
      .mocked(api.POST)
      .mock.calls.map((call) => String((call as unknown as unknown[])[0]))
    expect(paths[0]).toContain('/issue')
    expect(paths[1]).toContain('/artifacts')
  })

  /**
   * The one that matters. `issue()` is one transaction and does not produce the
   * artefacts — the caller does — so a failure of that second call leaves an invoice
   * that has its number and is fiscally complete, merely unprinted. Reporting "emission
   * failed" would be the more dangerous lie: it would send someone to reissue a
   * document that already exists in the register.
   */
  it('does not call a failed render a failed emission', async () => {
    vi.mocked(api.POST)
      .mockResolvedValueOnce(ok(ISSUED))
      .mockResolvedValueOnce(failed({ detail: 'typst non disponibile' }, 500))
    wrap(<InvoiceActions invoice={DRAFT} />)

    await userEvent.click(screen.getByRole('button', { name: /emetti/i }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Documento emesso'))
    await waitFor(() => expect(toast.warning).toHaveBeenCalled())
    const warning = String(vi.mocked(toast.warning).mock.calls[0]?.[0])
    expect(warning).toContain('emesso correttamente')
    expect(warning).toContain('Rigenera documenti')
    expect(vi.mocked(toast.error)).not.toHaveBeenCalled()
  })

  it('offers no issue button once the invoice is issued', () => {
    wrap(<InvoiceActions invoice={ISSUED} />)
    expect(screen.queryByRole('button', { name: /emetti/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /annulla/i })).toBeInTheDocument()
  })

  it('says annulment keeps the number, rather than offering a delete', async () => {
    wrap(<InvoiceActions invoice={ISSUED} />)
    await userEvent.click(screen.getByRole('button', { name: /^annulla$/i }))
    expect(screen.getByText(/Il numero resta nel registro/)).toBeInTheDocument()
  })

  it('hides the XML and regenerate actions for an invoice imported from Acme', () => {
    const imported = { ...ISSUED, importata_da: 'acme' } as Invoice
    wrap(<InvoiceActions invoice={imported} />)
    expect(screen.queryByRole('button', { name: /XML FatturaPA/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /Rigenera/i })).toBeNull()
    // The PDF stays: for an imported invoice it is the original document, not one
    // pigroCRM produced, so there is nothing to regenerate but nothing to hide either.
    expect(screen.getByRole('button', { name: /^PDF$/i })).toBeInTheDocument()
  })

  it('shows the "imported from Acme" badge next to the state badge', () => {
    const imported = { ...ISSUED, importata_da: 'acme' } as Invoice
    wrap(<InvoiceStateBadge invoice={imported} />)
    expect(screen.getByText(/importata da Acme/i)).toBeInTheDocument()
  })
})
