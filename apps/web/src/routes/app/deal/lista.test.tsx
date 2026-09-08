/**
 * The deal list's header and filter row (design spec §4).
 *
 * The two chips are the two dashboard drill-throughs this list has always had -- no new
 * filter is invented here. They matter more than an ordinary filter chip: the URL is
 * what carries them (criterion 2 -- the same predicate the dashboard counted, evaluated
 * on the server), so a chip has to *navigate* rather than set local state, and it must
 * stay pressed for whichever one the URL arrived with. A chip that looked pressed while
 * the list behind it was unfiltered would be the page lying about what it shows.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { DealsList } from './lista'

const navigate = vi.fn()

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return {
    ...actual,
    useNavigate: () => navigate,
    Link: ({ children }: { children: ReactNode }) => <a href="#">{children}</a>,
  }
})

const mockGet = vi.spyOn(api, 'GET')

beforeEach(() => {
  navigate.mockReset()
  mockGet.mockReset()
  mockGet.mockImplementation((() =>
    Promise.resolve({
      data: { items: [], next_cursor: null, custom_fields: [] },
      response: new Response(null, { status: 200 }),
    })) as never)
})

function renderList(filters: { fatturato_non_vinto?: boolean; da_fatturare?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <DealsList initialSearch="" filters={filters} />
    </QueryClientProvider>,
  )
}

describe('the deal list', () => {
  it('opens with its title as the page heading', async () => {
    renderList()
    expect(await screen.findByRole('heading', { level: 1, name: 'Deal' })).toBeInTheDocument()
  })

  it('offers the Kanban view as its header action', async () => {
    renderList()
    expect(await screen.findByRole('link', { name: /vista kanban/i })).toBeInTheDocument()
  })

  it('shows both drill-throughs as chips, none pressed on an unfiltered list', async () => {
    renderList()
    const filters = await screen.findByRole('search')
    expect(within(filters).getByRole('button', { name: 'Tutti' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(
      within(filters).getByRole('button', { name: 'Fatturato ma non vinto' }),
    ).toHaveAttribute('aria-pressed', 'false')
    expect(within(filters).getByRole('button', { name: 'Vinto ma da fatturare' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
  })

  it('keeps the chip of the filter the URL arrived with pressed', async () => {
    renderList({ da_fatturare: true })
    const filters = await screen.findByRole('search')
    expect(within(filters).getByRole('button', { name: 'Vinto ma da fatturare' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(within(filters).getByRole('button', { name: 'Tutti' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
  })

  it('navigates rather than filtering locally, because the server evaluates the predicate', async () => {
    renderList()
    const filters = await screen.findByRole('search')
    await userEvent.click(within(filters).getByRole('button', { name: 'Fatturato ma non vinto' }))
    expect(navigate).toHaveBeenCalledWith({
      to: '/app/deal/lista',
      search: { fatturato_non_vinto: true },
    })
  })

  it('clears the filter when the pressed chip is pressed again', async () => {
    renderList({ fatturato_non_vinto: true })
    const filters = await screen.findByRole('search')
    await userEvent.click(within(filters).getByRole('button', { name: 'Fatturato ma non vinto' }))
    expect(navigate).toHaveBeenCalledWith({ to: '/app/deal/lista', search: {} })
  })

  it('still states in words what an active filter is hiding', async () => {
    renderList({ da_fatturare: true })
    expect(await screen.findByRole('status')).toHaveTextContent(/solo i deal vinti/i)
  })
})
