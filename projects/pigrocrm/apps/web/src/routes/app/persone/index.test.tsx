/**
 * The people list's header and filter row (design spec §4). Same three assertions as
 * `clienti/index.test.tsx`, on the page next to it: the title and «Nuova persona» come
 * from `PageHeader`, and the search box lives in the filter row above the table. The
 * «Azienda» select is new: it navigates rather than filtering locally (same reasoning
 * as `deal/lista.test.tsx`'s chips) because `customer_id` is a real API filter
 * (`GET /api/people?customer_id=`), and its value has to survive a remount the same way
 * the URL's own `?search=` term does.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { PeoplePage } from './index'

const navigate = vi.fn()

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return { ...actual, useNavigate: () => navigate }
})

vi.mock('@/lib/auth', () => ({ useCanWrite: () => true }))

const mockGet = vi.spyOn(api, 'GET')

function customerPage(items: { id: string; ragione_sociale: string }[]) {
  return Promise.resolve({
    data: { items, next_cursor: null },
    response: new Response(null, { status: 200 }),
  }) as never
}

beforeEach(() => {
  navigate.mockReset()
  mockGet.mockReset()
  mockGet.mockImplementation(((path: string) => {
    if (path === '/api/customers') {
      return customerPage([
        { id: 'cust-zeta', ragione_sociale: 'Zeta Srl' },
        { id: 'cust-acme', ragione_sociale: 'ACME Srl' },
      ])
    }
    return Promise.resolve({
      data: { items: [], next_cursor: null, custom_fields: [] },
      response: new Response(null, { status: 200 }),
    })
  }) as never)
})

function renderPage(customerId?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <PeoplePage initialSearch="" customerId={customerId} />
    </QueryClientProvider>,
  )
}

/** The last `?customer_id=` the page asked `GET /api/people` for, or `undefined`
 *  when it asked for none. */
function lastRequestedCustomerId(): unknown {
  const calls = mockGet.mock.calls.filter((call) => call[0] === '/api/people')
  const last = calls[calls.length - 1]?.[1] as
    | { params?: { query?: Record<string, unknown> } }
    | undefined
  return last?.params?.query?.customer_id
}

/** What the page asks the router to make of the URL it is already on -- an updater,
 *  not a literal object, the same contract `deal/lista.test.tsx`'s `nextSearch` checks,
 *  so the `?search=` term the box may hold survives a company chosen from the select. */
function nextSearch(previous: Record<string, unknown>): Record<string, unknown> {
  const call = navigate.mock.calls.at(-1)?.[0] as {
    search: (prev: Record<string, unknown>) => Record<string, unknown>
  }
  expect(typeof call.search).toBe('function')
  return call.search(previous)
}

describe('the people list', () => {
  it('opens with its title as the page heading', async () => {
    renderPage()
    expect(await screen.findByRole('heading', { level: 1, name: 'Persone' })).toBeInTheDocument()
  })

  it('offers its primary action in the header', async () => {
    renderPage()
    expect(await screen.findByRole('button', { name: /nuova persona/i })).toBeInTheDocument()
  })

  it('puts the search box in the filter row', async () => {
    renderPage()
    const filters = await screen.findByRole('search')
    expect(within(filters).getByPlaceholderText(/cerca per nome/i)).toBeInTheDocument()
  })

  it('offers an «Azienda» select in the filter row, «Tutte le aziende» to begin with', async () => {
    renderPage()
    const filters = await screen.findByRole('search')
    expect(within(filters).getByLabelText('Filtra per azienda')).toHaveTextContent(
      'Tutte le aziende',
    )
    expect(lastRequestedCustomerId()).toBeUndefined()
  })

  it('lists the companies sorted by ragione sociale, not by API order', async () => {
    renderPage()
    const filters = await screen.findByRole('search')
    await userEvent.click(within(filters).getByRole('combobox', { name: 'Filtra per azienda' }))
    const options = await screen.findAllByRole('option')
    expect(options.map((option) => option.textContent)).toEqual([
      'Tutte le aziende',
      'ACME Srl',
      'Zeta Srl',
    ])
  })

  it('reads its initial company from the URL', async () => {
    renderPage('cust-acme')
    const filters = await screen.findByRole('search')
    expect(await within(filters).findByText('ACME Srl')).toBeInTheDocument()
    expect(lastRequestedCustomerId()).toBe('cust-acme')
  })

  it('navigates with the chosen company rather than filtering locally', async () => {
    renderPage()
    const filters = await screen.findByRole('search')
    await userEvent.click(within(filters).getByRole('combobox', { name: 'Filtra per azienda' }))
    await userEvent.click(await screen.findByRole('option', { name: 'ACME Srl' }))

    expect(nextSearch({ search: 'mario' })).toEqual({
      search: 'mario',
      customer_id: 'cust-acme',
    })
  })

  it('clears the company filter with «Tutte le aziende»', async () => {
    renderPage('cust-acme')
    const filters = await screen.findByRole('search')
    await userEvent.click(within(filters).getByRole('combobox', { name: 'Filtra per azienda' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Tutte le aziende' }))

    expect(nextSearch({ customer_id: 'cust-acme' })).toEqual({})
  })
})
