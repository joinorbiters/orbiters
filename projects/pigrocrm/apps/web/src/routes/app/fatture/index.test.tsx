/**
 * The invoice list's own header and filter row (design spec §4).
 *
 * The page is what the revision changed: the title and the primary action moved into
 * `PageHeader`, and the «stato» filter -- a `Select` until now -- became the row of
 * `rounded-full` chips the reference screenshots use. The chips are the part worth a
 * test: they are the only filter on this screen a user drives, and a chip that looks
 * pressed while the list behind it is unfiltered is a page lying about what it shows.
 *
 * `api.GET` is spied on directly rather than `useInvoices` being mocked, mirroring
 * `clienti/$customerId.test.tsx`: what is asserted is the query the page actually
 * sends.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { InvoicesList } from './index'

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    // A real `Link` needs a router context this component test has no reason to stand
    // up; what matters here is that the page renders one, not what TanStack does with
    // it.
    Link: ({ children }: { children: ReactNode }) => <a href="#">{children}</a>,
  }
})

const mockGet = vi.spyOn(api, 'GET')

function ok(data: unknown) {
  return Promise.resolve({ data, response: new Response(null, { status: 200 }) }) as never
}

beforeEach(() => {
  mockGet.mockReset()
  mockGet.mockImplementation((() => ok({ items: [], next_cursor: null })) as never)
})

function renderList(scadute?: boolean): ReactElement {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <InvoicesList scadute={scadute} />
    </QueryClientProvider>,
  )
  return <></>
}

/** One issued invoice as the API sends it, with whatever a test needs changed. */
function invoice(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'f1',
    anno: 2026,
    numero: 7,
    riferimento: null,
    tipo: 'fattura',
    stato: 'emessa',
    stato_pagamento: 'da_incassare',
    data_emissione: '2026-08-20',
    competenza_da: null,
    competenza_a: null,
    totale: '1500.00',
    customer_ragione_sociale: 'ACME S.r.l.',
    ...overrides,
  }
}

/** Makes the list endpoint answer these rows; every other endpoint stays empty. */
function mockInvoices(items: Record<string, unknown>[]): void {
  mockGet.mockImplementation(((path: string) =>
    path === '/api/invoices'
      ? ok({ items, next_cursor: null })
      : ok({ items: [], next_cursor: null })) as never)
}

/** The `stato` the page last asked the API for, or `undefined` when it asked for none. */
function lastRequestedStato(): unknown {
  const calls = mockGet.mock.calls.filter((call) => call[0] === '/api/invoices')
  const last = calls[calls.length - 1]?.[1] as
    | { params?: { query?: Record<string, unknown> } }
    | undefined
  return last?.params?.query?.stato
}

describe('the invoice list', () => {
  it('opens with its title as the page heading', async () => {
    renderList()
    expect(await screen.findByRole('heading', { level: 1, name: 'Fatture' })).toBeInTheDocument()
  })

  it('offers its primary action in the header', async () => {
    renderList()
    expect(await screen.findByRole('button', { name: /nuova fattura/i })).toBeInTheDocument()
  })

  it('shows one state chip per invoice state, «Tutte» pressed to begin with', async () => {
    renderList()
    const filters = await screen.findByRole('search')
    expect(within(filters).getByRole('button', { name: 'Tutte' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    for (const label of ['Bozza', 'Emessa', 'Annullata', 'Confermata', 'Consumata']) {
      expect(within(filters).getByRole('button', { name: label })).toHaveAttribute(
        'aria-pressed',
        'false',
      )
    }
  })

  it('asks the API for the state whose chip is pressed', async () => {
    renderList()
    const filters = await screen.findByRole('search')
    expect(lastRequestedStato()).toBeUndefined()

    await userEvent.click(within(filters).getByRole('button', { name: 'Emessa' }))
    expect(within(filters).getByRole('button', { name: 'Emessa' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(lastRequestedStato()).toBe('emessa')
  })

  it('clears the state filter when the pressed chip is pressed again', async () => {
    renderList()
    const filters = await screen.findByRole('search')
    await userEvent.click(within(filters).getByRole('button', { name: 'Emessa' }))
    await userEvent.click(within(filters).getByRole('button', { name: 'Emessa' }))

    expect(lastRequestedStato()).toBeUndefined()
    expect(within(filters).getByRole('button', { name: 'Tutte' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('keeps the type filter as a select in the same row', async () => {
    renderList()
    const filters = await screen.findByRole('search')
    expect(within(filters).getByLabelText('Filtra per tipo')).toBeInTheDocument()
  })

  /** The list is the one screen that mixes customers, so it is the one that says whose
   *  invoice each row is (ORB-98). The tab inside a customer's page does not: see
   *  `InvoicesTab.test.tsx`. */
  it('says which customer each invoice belongs to', async () => {
    mockInvoices([invoice()])
    renderList()
    expect(await screen.findByRole('columnheader', { name: 'Cliente' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'ACME S.r.l.' })).toBeInTheDocument()
  })

  it('says which period each invoice is about, beside its date (ORB-126)', async () => {
    mockInvoices([
      invoice({
        data_emissione: '2026-09-02',
        competenza_da: '2026-08-01',
        competenza_a: '2026-08-31',
      }),
    ])
    renderList()
    const headers = (await screen.findAllByRole('columnheader')).map((h) => h.textContent)
    expect(headers.indexOf('Competenza')).toBe(headers.indexOf('Data') + 1)
    expect(screen.getByRole('cell', { name: '01/08/2026 - 31/08/2026' })).toBeInTheDocument()
  })

  it('still explains the «scadute» drill-through it arrives with', async () => {
    renderList(true)
    expect(await screen.findByRole('status')).toHaveTextContent(/scadute e non incassate/i)
  })
})
