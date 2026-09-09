import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { toast } from 'sonner'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { NewProformaButton } from './NewProformaDialog'

const navigate = vi.fn()

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return { ...actual, useNavigate: () => navigate }
})

// The house pattern (features/invoices/InvoiceActions.test.tsx): the client's methods
// are replaced, `unwrap`/`toProblem` are the real ones -- what is under test is this
// dialog's handling of what a real API answer produces, not a reimplementation of it.
vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn(), PUT: vi.fn(), PATCH: vi.fn() } }
})
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() } }))

function ok(data: unknown) {
  return Promise.resolve({ data, response: new Response(null, { status: 200 }) }) as never
}

function failed(error: unknown, status: number) {
  return Promise.resolve({ error, response: new Response(null, { status }) }) as never
}

const CUSTOMERS = [
  { id: 'cust-1', ragione_sociale: 'ACME Srl' },
  { id: 'cust-2', ragione_sociale: 'Beta Snc' },
]

// `customer_ragione_sociale` is on the wire shape (`DealRead`, denormalised there on
// purpose), which is what lets the deal-fixed dialog name the customer without asking
// for it.
const DEALS = [
  { id: 'deal-1', nome: 'Sito vetrina', customer_id: 'cust-1', customer_ragione_sociale: 'ACME Srl' },
  { id: 'deal-2', nome: 'App interna', customer_id: 'cust-1', customer_ragione_sociale: 'ACME Srl' },
]

/** Every GET this dialog can make, answered by path. `useDeals` walks a cursor, so its
 *  page has to carry an explicit `next_cursor: null` or it would loop. */
function mockGets() {
  vi.mocked(api.GET).mockImplementation(((path: string) => {
    if (path === '/api/customers') return ok({ items: CUSTOMERS, next_cursor: null })
    if (path === '/api/deals') return ok({ items: DEALS, next_cursor: null })
    // The two single-record reads the *fixed* variants make, to name in words what the
    // pickers would otherwise have offered as a choice. Both are cache hits in the app
    // -- the page that opened the dialog has already read them.
    if (path === '/api/customers/{customer_id}') return ok(CUSTOMERS[0])
    if (path === '/api/deals/{deal_id}') return ok(DEALS[0])
    return ok({ items: [], next_cursor: null })
  }) as never)
}

beforeEach(() => {
  vi.mocked(api.GET).mockReset()
  vi.mocked(api.POST).mockReset()
  vi.mocked(toast.success).mockReset()
  navigate.mockReset()
  mockGets()
})

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

type ButtonProps = Parameters<typeof NewProformaButton>[0]

async function open(props: ButtonProps = {}) {
  renderWithClient(<NewProformaButton {...props} />)
  await userEvent.click(screen.getByRole('button', { name: 'Nuova fattura' }))
}

async function chooseCustomer(name: string) {
  await userEvent.click(screen.getByLabelText(/^Cliente/))
  await userEvent.click(await screen.findByRole('option', { name }))
}

function body(): Record<string, unknown> {
  const [first] = vi.mocked(api.POST).mock.calls
  if (!first) throw new Error('POST /api/invoices was never called')
  return (first[1] as { body: Record<string, unknown> }).body
}

describe('NewProformaButton', () => {
  it('opens a dialog that says what it will create', async () => {
    await open()

    // The button carries the word the owner asked for ("Nuova fattura", on the Fatture
    // page); the dialog is where it says a *proforma* is what comes out, since the
    // number is only assigned at emission.
    expect(await screen.findByRole('dialog')).toHaveTextContent('Nuova proforma')
    expect(screen.getByLabelText(/^Causale/)).toBeInTheDocument()
  })

  it('starts with exactly one line, quantity 1', async () => {
    await open()

    expect(screen.getByLabelText('Quantità riga 1')).toHaveValue('1')
    expect(screen.queryByLabelText('Quantità riga 2')).not.toBeInTheDocument()
  })

  it('refuses to post without a customer', async () => {
    await open()
    await userEvent.type(screen.getByLabelText(/^Causale/), 'Consulenza settembre')
    await userEvent.type(screen.getByLabelText('Descrizione riga 1'), 'Analisi')
    await userEvent.type(screen.getByLabelText('Prezzo unitario riga 1'), '150.00')
    await userEvent.click(screen.getByRole('button', { name: 'Crea proforma' }))

    expect(screen.getByText('Scegli il cliente da fatturare.')).toBeInTheDocument()
    expect(api.POST).not.toHaveBeenCalled()
  })

  it('refuses to post without a causale', async () => {
    await open()
    await chooseCustomer('ACME Srl')
    await userEvent.type(screen.getByLabelText('Descrizione riga 1'), 'Analisi')
    await userEvent.type(screen.getByLabelText('Prezzo unitario riga 1'), '150.00')
    await userEvent.click(screen.getByRole('button', { name: 'Crea proforma' }))

    expect(screen.getByText('La causale è obbligatoria.')).toBeInTheDocument()
    expect(api.POST).not.toHaveBeenCalled()
  })

  it('refuses to post a document with no priced line', async () => {
    // A proforma with no lines is a zero-total document, and the owner would only
    // discover it on the detail page. The API accepts it (`righe` defaults to empty);
    // this form does not offer it.
    await open()
    await chooseCustomer('ACME Srl')
    await userEvent.type(screen.getByLabelText(/^Causale/), 'Consulenza settembre')
    await userEvent.click(screen.getByRole('button', { name: 'Crea proforma' }))

    expect(
      screen.getByText('Serve almeno una riga con descrizione e prezzo unitario.'),
    ).toBeInTheDocument()
    expect(api.POST).not.toHaveBeenCalled()
  })

  it('creates the proforma and goes to it, so it can be confirmed and issued', async () => {
    vi.mocked(api.POST).mockReturnValue(ok({ id: 'inv-9', tipo: 'proforma', stato: 'bozza' }))
    await open()
    await chooseCustomer('ACME Srl')
    await userEvent.type(screen.getByLabelText(/^Causale/), 'Consulenza settembre')
    await userEvent.type(screen.getByLabelText('Descrizione riga 1'), 'Analisi')
    await userEvent.clear(screen.getByLabelText('Quantità riga 1'))
    await userEvent.type(screen.getByLabelText('Quantità riga 1'), '2')
    await userEvent.type(screen.getByLabelText('Prezzo unitario riga 1'), '150.00')
    await userEvent.click(screen.getByRole('button', { name: 'Crea proforma' }))

    expect(body()).toEqual({
      customer_id: 'cust-1',
      tipo: 'proforma',
      causale: 'Consulenza settembre',
      righe: [{ descrizione: 'Analisi', quantita: '2', prezzo_unitario: '150.00' }],
    })
    expect(navigate).toHaveBeenCalledWith({
      to: '/app/fatture/$invoiceId',
      params: { invoiceId: 'inv-9' },
    })
    expect(toast.success).toHaveBeenCalled()
  })

  it('sends the chosen deal, and offers only that customer’s deals', async () => {
    vi.mocked(api.POST).mockReturnValue(ok({ id: 'inv-9' }))
    await open()
    await chooseCustomer('ACME Srl')

    // The deal picker asks the API for that customer's deals rather than filtering a
    // full list in the browser: `DealListQuery` has `customer_id`, and the repository
    // is the only thing that can see a deal this page never fetched.
    await userEvent.click(screen.getByLabelText(/^Deal/))
    await userEvent.click(await screen.findByRole('option', { name: 'App interna' }))
    expect(api.GET).toHaveBeenCalledWith(
      '/api/deals',
      expect.objectContaining({
        params: expect.objectContaining({
          query: expect.objectContaining({ customer_id: 'cust-1' }),
        }),
      }),
    )

    await userEvent.type(screen.getByLabelText(/^Causale/), 'Sprint 3')
    await userEvent.type(screen.getByLabelText('Descrizione riga 1'), 'Sviluppo')
    await userEvent.type(screen.getByLabelText('Prezzo unitario riga 1'), '80')
    await userEvent.click(screen.getByRole('button', { name: 'Crea proforma' }))

    expect(body()).toMatchObject({ customer_id: 'cust-1', deal_id: 'deal-2' })
  })

  it('adds and removes lines, and previews the imponibile as it goes', async () => {
    await open()
    await userEvent.type(screen.getByLabelText('Descrizione riga 1'), 'Analisi')
    await userEvent.type(screen.getByLabelText('Prezzo unitario riga 1'), '150.00')
    await userEvent.click(screen.getByRole('button', { name: 'Aggiungi riga' }))
    await userEvent.type(screen.getByLabelText('Descrizione riga 2'), 'Sviluppo')
    await userEvent.type(screen.getByLabelText('Prezzo unitario riga 2'), '99.90')

    expect(screen.getByText(/249,90/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Rimuovi riga 2' }))
    expect(screen.queryByLabelText('Descrizione riga 2')).not.toBeInTheDocument()
    expect(screen.getByText(/150,00/)).toBeInTheDocument()
  })

  it('shows the API’s own refusal instead of a generic failure', async () => {
    vi.mocked(api.POST).mockReturnValue(
      failed(
        {
          type: 'https://pigrocrm.dev/errors/conflict',
          title: 'Conflitto',
          status: 409,
          detail: 'il deal non appartiene a questo cliente',
          code: 'conflict',
        },
        409,
      ),
    )
    await open()
    await chooseCustomer('ACME Srl')
    await userEvent.type(screen.getByLabelText(/^Causale/), 'Consulenza')
    await userEvent.type(screen.getByLabelText('Descrizione riga 1'), 'Analisi')
    await userEvent.type(screen.getByLabelText('Prezzo unitario riga 1'), '150')
    await userEvent.click(screen.getByRole('button', { name: 'Crea proforma' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'il deal non appartiene a questo cliente',
    )
    expect(navigate).not.toHaveBeenCalled()
  })
})

/**
 * The same dialog opened from a customer's Fatture tab or from a deal's header, where
 * the answer to «per chi?» is already on screen. What is fixed is shown as text rather
 * than as a disabled control: a select nobody can use still reads as a decision left to
 * make, and the id travels in the body either way.
 */
describe('NewProformaButton, opened from a record that already answers the question', () => {
  it('does not ask for the customer when it already knows one, and sends it anyway', async () => {
    vi.mocked(api.POST).mockReturnValue(ok({ id: 'inv-9' }))
    await open({ customerId: 'cust-1' })

    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(screen.queryByLabelText(/^Cliente/)).not.toBeInTheDocument()
    expect(await screen.findByText('ACME Srl')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText(/^Causale/), 'Consulenza settembre')
    await userEvent.type(screen.getByLabelText('Descrizione riga 1'), 'Analisi')
    await userEvent.type(screen.getByLabelText('Prezzo unitario riga 1'), '150.00')
    await userEvent.click(screen.getByRole('button', { name: 'Crea proforma' }))

    expect(body()).toMatchObject({ customer_id: 'cust-1' })
    expect(body()).not.toHaveProperty('deal_id')
  })

  it('still offers that customer’s deals when only the customer is fixed', async () => {
    vi.mocked(api.POST).mockReturnValue(ok({ id: 'inv-9' }))
    await open({ customerId: 'cust-1' })

    // The combination the customer's Fatture tab ships: the customer is settled, the
    // deal is not, and the list is still the server-filtered one.
    await userEvent.click(await screen.findByLabelText(/^Deal/))
    await userEvent.click(await screen.findByRole('option', { name: 'App interna' }))
    expect(api.GET).toHaveBeenCalledWith(
      '/api/deals',
      expect.objectContaining({
        params: expect.objectContaining({
          query: expect.objectContaining({ customer_id: 'cust-1' }),
        }),
      }),
    )

    await userEvent.type(screen.getByLabelText(/^Causale/), 'Sprint 3')
    await userEvent.type(screen.getByLabelText('Descrizione riga 1'), 'Sviluppo')
    await userEvent.type(screen.getByLabelText('Prezzo unitario riga 1'), '80')
    await userEvent.click(screen.getByRole('button', { name: 'Crea proforma' }))

    expect(body()).toMatchObject({ customer_id: 'cust-1', deal_id: 'deal-2' })
  })

  it('names the customer from the deal it was opened from, without asking for it', async () => {
    await open({
      customerId: 'cust-1',
      dealId: 'deal-1',
      prefill: { descrizione: 'Sito vetrina', importo: '4500.00' },
    })

    // `DealRead.customer_ragione_sociale` carries the name, and the deal page has
    // already read the deal -- so the dialog opens with both parties named and never
    // touches `/api/customers/{customer_id}`, which from that page would be a cold read
    // behind a «…» placeholder.
    expect(await screen.findByText('ACME Srl')).toBeInTheDocument()
    expect(api.GET).not.toHaveBeenCalledWith('/api/customers/{customer_id}', expect.anything())
  })

  it('fixes the deal too, and starts from the deal’s own name and expected value', async () => {
    vi.mocked(api.POST).mockReturnValue(ok({ id: 'inv-9' }))
    await open({
      customerId: 'cust-1',
      dealId: 'deal-1',
      prefill: { descrizione: 'Sito vetrina', importo: '4500.00' },
    })

    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(screen.queryByLabelText(/^Deal/)).not.toBeInTheDocument()
    expect(screen.getByLabelText('Descrizione riga 1')).toHaveValue('Sito vetrina')
    expect(screen.getByLabelText('Quantità riga 1')).toHaveValue('1')
    expect(screen.getByLabelText('Prezzo unitario riga 1')).toHaveValue('4500.00')

    await userEvent.type(screen.getByLabelText(/^Causale/), 'Acconto')
    await userEvent.click(screen.getByRole('button', { name: 'Crea proforma' }))

    expect(body()).toEqual({
      customer_id: 'cust-1',
      deal_id: 'deal-1',
      tipo: 'proforma',
      causale: 'Acconto',
      righe: [{ descrizione: 'Sito vetrina', quantita: '1', prezzo_unitario: '4500.00' }],
    })
  })

  it('leaves the pre-filled line editable, because a deal’s value is rarely the invoice’s', async () => {
    vi.mocked(api.POST).mockReturnValue(ok({ id: 'inv-9' }))
    await open({
      customerId: 'cust-1',
      dealId: 'deal-1',
      prefill: { descrizione: 'Sito vetrina', importo: '4500.00' },
    })

    await userEvent.clear(screen.getByLabelText('Prezzo unitario riga 1'))
    await userEvent.type(screen.getByLabelText('Prezzo unitario riga 1'), '1500.00')
    await userEvent.type(screen.getByLabelText(/^Causale/), 'Primo acconto')
    await userEvent.click(screen.getByRole('button', { name: 'Crea proforma' }))

    expect(body()).toMatchObject({
      righe: [{ descrizione: 'Sito vetrina', quantita: '1', prezzo_unitario: '1500.00' }],
    })
  })

  it('starts from an empty line when the deal carries no expected value', async () => {
    await open({
      customerId: 'cust-1',
      dealId: 'deal-1',
      prefill: { descrizione: 'Sito vetrina', importo: '' },
    })

    expect(screen.getByLabelText('Descrizione riga 1')).toHaveValue('Sito vetrina')
    expect(screen.getByLabelText('Prezzo unitario riga 1')).toHaveValue('')
  })
})
