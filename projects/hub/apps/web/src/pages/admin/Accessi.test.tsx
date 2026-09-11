import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AdminAccessi } from './Accessi'

vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, params, children, ...rest }: { to: string; params?: Record<string, string>; children: React.ReactNode }) => (
    <a href={params ? to.replace('$id', params.id!) : to} {...rest}>{children}</a>
  ),
}))

function answer(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <AdminAccessi />
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('the Accessi page', () => {
  it('shows the three numbers and the latest logins, each naming the member (ORB-158)', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      answer(200, {
        totale: 5,
        membri: 2,
        membri_totali: 4,
        ultimi_7_giorni: 3,
        recenti: [
          { id: 'l-1', freelancer_id: 'f-1', nome: 'Ada', cognome: 'Lovelace', email: 'ada@studio.it', logged_at: '2026-09-11T12:04:00Z' },
        ],
      }),
    )
    mount()
    const who = await screen.findByRole('link', { name: 'Ada Lovelace' })
    expect(who).toHaveAttribute('href', '/admin/freelance/f-1')
    expect(spy.mock.calls[0]![0]).toBe('/api/hub/logins')
    expect(screen.getByRole('heading', { name: /Accessi/ })).toHaveTextContent('5')
    expect(screen.getByText('Accessi', { selector: 'dt' }).nextElementSibling).toHaveTextContent('5')
    expect(screen.getByText('Membri entrati').nextElementSibling).toHaveTextContent('2su 4')
    expect(screen.getByText('Ultimi 7 giorni').nextElementSibling).toHaveTextContent('3')
    expect(screen.getByText('ada@studio.it')).toBeInTheDocument()
    expect(who.closest('tr')).toHaveTextContent(/11 set 2026/)
  })

  it('says when nobody has come in yet', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      answer(200, { totale: 0, membri: 0, membri_totali: 4, ultimi_7_giorni: 0, recenti: [] }),
    )
    mount()
    await screen.findByText('Nessun accesso ancora.')
    expect(screen.getByText('Membri entrati').nextElementSibling).toHaveTextContent('0su 4')
  })

  it('says when the numbers cannot be read', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(answer(500, { detail: 'boom' }))
    mount()
    await screen.findByText('Non riesco a leggere gli accessi.')
  })
})
