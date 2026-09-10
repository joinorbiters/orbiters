import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AdminPigro } from './Pigro'

vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, params, children, ...rest }: { to: string; params?: Record<string, string>; children: React.ReactNode }) => (
    <a href={params ? to.replace('$id', params.id!) : to} {...rest}>{children}</a>
  ),
}))

const ADA = {
  slug: 'studio-ada',
  owner_email: 'ada@studio.it',
  created_at: '2026-09-10T09:00:00Z',
  url: 'https://pigro.joinorbiters.com/studio-ada/app/',
  membro: { id: 'f-1', nome: 'Ada', cognome: 'Lovelace' },
}
const BOB = {
  slug: 'bob-dev',
  owner_email: 'bob@example.org',
  created_at: '2026-09-09T09:00:00Z',
  url: 'https://pigro.joinorbiters.com/bob-dev/app/',
  membro: null,
}

function answer(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <AdminPigro />
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('the Istanze Pigro page', () => {
  it('lists every space with a link to it, and names the member who owns one', async () => {
    // ORB-142: which spaces exist and whose they are.
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(answer(200, { totale: 2, items: [ADA, BOB] }))
    mount()
    const space = await screen.findByRole('link', { name: 'studio-ada' })
    expect(space).toHaveAttribute('href', 'https://pigro.joinorbiters.com/studio-ada/app/')
    expect(spy.mock.calls[0]![0]).toBe('/api/hub/pigro/istanze')
    // Ada is a member: her name links to her card, and her address is beside it.
    expect(screen.getByRole('link', { name: 'Ada Lovelace' })).toHaveAttribute('href', '/admin/freelance/f-1')
    expect(screen.getByText('ada@studio.it')).toBeInTheDocument()
    // Bob is not: the address is all there is, and nothing claims otherwise.
    expect(screen.getByText('bob@example.org')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /bob/i })).toHaveAttribute('href', 'https://pigro.joinorbiters.com/bob-dev/app/')
    expect(screen.getByRole('heading', { name: /Istanze Pigro/ })).toHaveTextContent('2')
  })

  it('says the registry is not configured when the API answers 503 with its sentence', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      answer(503, { detail: 'Il registro di Pigro non è configurato: manca ORBITERS_PIGRO_REGISTRY_TOKEN.' }),
    )
    mount()
    await screen.findByText('Il registro di Pigro non è configurato: manca ORBITERS_PIGRO_REGISTRY_TOKEN.')
  })

  it('says when there is nothing yet', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(answer(200, { totale: 0, items: [] }))
    mount()
    await screen.findByText('Nessuna istanza ancora.')
  })
})
