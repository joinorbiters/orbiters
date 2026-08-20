import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import { NewFromTemplateDialog, variablesToFields } from './NewFromTemplateDialog'
import type { Template, TemplateDescription } from './queries'

const TEMPLATE: Template = {
  id: 't-1',
  nome: 'Consulenza CTO',
  tipo: 'offerta',
  corpo_markdown: 'Oggetto: {{oggetto}}',
  variabili_dichiarate: [],
  attivo: true,
  created_at: '2026-08-10T09:00:00Z',
  updated_at: '2026-08-10T09:00:00Z',
}

const DESCRIPTION: TemplateDescription = {
  id: 't-1',
  nome: 'Consulenza CTO',
  tipo: 'offerta',
  variabili: [
    { nome: 'oggetto', etichetta: 'Oggetto', tipo: 'text', obbligatoria: true, options: [] },
    { nome: 'urgente', etichetta: 'Urgente', tipo: 'checkbox', obbligatoria: false, options: [] },
  ],
  percorsi_usati: [['oggetto'], ['cliente', 'ragione_sociale']],
  variabili_non_usate: [],
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

// `api.GET`/`api.POST` are spied on directly, not `globalThis.fetch` -- see
// queries.test.tsx and task-14-report.md for why a `globalThis.fetch` mock never
// intercepts a request made through the shared `openapi-fetch` client. Each spy
// routes on the literal (un-interpolated) path template `api.GET`/`api.POST` is
// called with, e.g. `'/api/templates/{template_id}/describe'`, which is stable
// regardless of which real template id is substituted in.
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

function routeGet(routes: Record<string, unknown>) {
  mockGet.mockImplementation((path: unknown) => {
    const match = Object.keys(routes).find((key) => String(path).includes(key))
    return match ? ok(routes[match]) : ok(undefined)
  })
}

describe('variablesToFields', () => {
  it('maps a declared variable onto the FieldDefinition DynamicFieldRenderer expects', () => {
    expect(variablesToFields(DESCRIPTION.variabili)).toEqual([
      { key: 'oggetto', label: 'Oggetto', type: 'text', required: true, options: [] },
      { key: 'urgente', label: 'Urgente', type: 'checkbox', required: false, options: [] },
    ])
  })
})

describe('NewFromTemplateDialog', () => {
  it('lists the available templates', async () => {
    routeGet({ '/api/templates': { items: [TEMPLATE], next_cursor: null } })
    render(<NewFromTemplateDialog open onOpenChange={() => {}} owner={{ customerId: 'c-1' }} />, {
      wrapper,
    })
    expect(await screen.findByText('Consulenza CTO')).toBeInTheDocument()
  })

  it('shows the declared variables once a template is chosen', async () => {
    routeGet({
      '/describe': DESCRIPTION,
      '/api/templates': { items: [TEMPLATE], next_cursor: null },
    })
    render(<NewFromTemplateDialog open onOpenChange={() => {}} owner={{ customerId: 'c-1' }} />, {
      wrapper,
    })
    await userEvent.click(await screen.findByText('Consulenza CTO'))
    expect(await screen.findByLabelText(/Oggetto/)).toBeInTheDocument()
    expect(await screen.findByLabelText(/Urgente/)).toBeInTheDocument()
  })

  it('sends an untouched checkbox as false, because create mode says so', async () => {
    routeGet({
      '/describe': DESCRIPTION,
      '/api/templates': { items: [TEMPLATE], next_cursor: null },
    })
    let sentBody: { variabili: Record<string, unknown> } | undefined
    mockPost.mockImplementation((path: unknown, options: unknown) => {
      if (String(path).includes('/preview')) return ok({ markdown: 'Oggetto: Advisory' })
      if (String(path).includes('/from-template')) {
        sentBody = (options as { body: { variabili: Record<string, unknown> } }).body
        return ok({ id: 'doc-1' })
      }
      return ok(undefined)
    })
    render(<NewFromTemplateDialog open onOpenChange={() => {}} owner={{ customerId: 'c-1' }} />, {
      wrapper,
    })
    await userEvent.click(await screen.findByText('Consulenza CTO'))
    await userEvent.type(await screen.findByLabelText(/Oggetto/), 'Advisory')
    await userEvent.type(screen.getByLabelText('Titolo'), 'Offerta 2026-01')
    await userEvent.click(screen.getByRole('button', { name: 'Genera' }))

    await waitFor(() => {
      expect(sentBody).toBeDefined()
      // `false` is a value, never a blank: an unchecked box the user looked at is an
      // answer, and `mode="create"` is what makes DynamicForm seed it.
      expect(sentBody?.variabili.urgente).toBe(false)
      expect(sentBody?.variabili.oggetto).toBe('Advisory')
    })
  })

  it('shows the preview the server rendered, never a client-side render', async () => {
    routeGet({
      '/describe': DESCRIPTION,
      '/api/templates': { items: [TEMPLATE], next_cursor: null },
    })
    mockPost.mockImplementation((path: unknown) =>
      String(path).includes('/preview') ? ok({ markdown: 'Oggetto: Advisory' }) : ok(undefined),
    )
    render(<NewFromTemplateDialog open onOpenChange={() => {}} owner={{ customerId: 'c-1' }} />, {
      wrapper,
    })
    await userEvent.click(await screen.findByText('Consulenza CTO'))
    await userEvent.type(await screen.findByLabelText(/Oggetto/), 'Advisory')
    await userEvent.click(screen.getByRole('button', { name: 'Anteprima' }))
    expect(await screen.findByText('Oggetto: Advisory')).toBeInTheDocument()
  })

  it('shows the server validation message on the offending field', async () => {
    routeGet({
      '/describe': DESCRIPTION,
      '/api/templates': { items: [TEMPLATE], next_cursor: null },
    })
    mockPost.mockImplementation((path: unknown) =>
      String(path).includes('/from-template')
        ? failed(
            {
              code: 'validation_failed',
              detail: 'template.oggetto: variabile obbligatoria mancante',
              field: 'oggetto',
              reason: 'variabile obbligatoria mancante: Oggetto',
            },
            422,
          )
        : ok(undefined),
    )
    render(<NewFromTemplateDialog open onOpenChange={() => {}} owner={{ customerId: 'c-1' }} />, {
      wrapper,
    })
    await userEvent.click(await screen.findByText('Consulenza CTO'))
    await userEvent.type(screen.getByLabelText('Titolo'), 'Offerta')
    await userEvent.click(screen.getByRole('button', { name: 'Genera' }))
    expect(await screen.findByText(/variabile obbligatoria mancante: Oggetto/)).toBeInTheDocument()
  })

  it('shows an error banner when the template list fails, not an empty list', async () => {
    mockGet.mockReturnValue(failed({ code: 'http_error', detail: 'Giù' }, 503))
    render(<NewFromTemplateDialog open onOpenChange={() => {}} owner={{ customerId: 'c-1' }} />, {
      wrapper,
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('Giù')
  })
})
