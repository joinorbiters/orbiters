import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DealDetail } from './$dealId'
import { api } from '@/lib/api'

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return {
    ...actual,
    useParams: () => ({ dealId: 'd1' }),
    useNavigate: () => vi.fn(),
    // The Preventivo card links to Analisi, and a real `Link` needs a router context
    // this test has no reason to build. The house stub (deal/lista.test.tsx,
    // fatture/index.test.tsx) renders it as a plain anchor.
    Link: ({ children }: { children: ReactNode }) => <a href="#">{children}</a>,
  }
})

// Hoisted so one test can flip it: the header's actions exist only for a writer, and
// everything else here is about what any reader sees.
const auth = vi.hoisted(() => ({ canWrite: false }))
vi.mock('@/lib/auth', () => ({ useCanWrite: () => auth.canWrite }))

// `api.GET` is spied on directly, mirroring `clienti/$customerId.test.tsx`: what
// is under test is this route's own handling of what the real `unwrap` produces,
// not a reimplementation of it. `DealDetail` also mounts `useEntitySchema` and
// `useStages` unconditionally -- both resolve to a harmless empty success below,
// since neither is ever read before the isError/404 guard under test here
// returns.
const mockGet = vi.spyOn(api, 'GET')

function ok(data: unknown) {
  return Promise.resolve({ data, response: new Response(null, { status: 200 }) }) as never
}
function failed(error: unknown, status: number) {
  return Promise.resolve({ error, response: new Response(null, { status }) }) as never
}

function mockDealFetch(result: ReturnType<typeof ok> | ReturnType<typeof failed>) {
  mockGet.mockImplementation(
    ((path: string) => (path === '/api/deals/{deal_id}' ? result : ok({ items: [] }))) as never,
  )
}

beforeEach(() => {
  mockGet.mockReset()
  auth.canWrite = false
})

/** Enough of a `DealRead` for the page to render past its guards. Every nullable field
 *  the Panoramica formats is present as `null`: absent is not the same as null to
 *  `formatDate`/`formatMoney`, which read the string they are handed. */
const DEAL = {
  id: 'd1',
  nome: 'Sito vetrina',
  customer_id: 'c1',
  customer_ragione_sociale: 'ACME Srl',
  pipeline_stage_id: 's1',
  valore_previsto: '4500.00',
  probabilita: 50,
  data_chiusura_prevista: null,
  ore_preventivate: null,
  valore_preventivato: null,
  tariffa_oraria: null,
  owner_id: null,
  note: null,
  chiuso_il: null,
  custom_fields: {},
} as never

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('DealDetail', () => {
  it('shows "Deal non trovato" for a genuine 404', async () => {
    mockDealFetch(
      failed(
        { type: 'about:blank', title: 'Non trovato', status: 404, detail: 'deal non trovato', code: 'not_found' },
        404,
      ),
    )
    renderWithClient(<DealDetail />)
    expect(await screen.findByText('Deal non trovato.')).toBeInTheDocument()
  })

  /**
   * The bug this guards against: before this fix, `if (!deal) return <p>Deal
   * non trovato.</p>` fired for *any* failed fetch, not only a real 404 -- a
   * 500, a 502 or a dropped connection told the user the record does not
   * exist. This reuses `QueryErrorBanner`, the same surface `DataTable` and
   * `Timeline` already show for a failed request everywhere else in this app,
   * rather than inventing a fourth way to say "something went wrong".
   */
  it('shows the failed-request banner, not "Deal non trovato", when the fetch fails for a reason other than 404', async () => {
    mockDealFetch(failed({ code: 'http_error', detail: 'Il server non risponde.', status: 503 }, 503))
    renderWithClient(<DealDetail />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Il server non risponde.')
    expect(screen.queryByText('Deal non trovato.')).not.toBeInTheDocument()
  })

  /**
   * The commonest invoice of all is the one a deal has just earned, and every field it
   * needs is on this page already. The action is in the header rather than on the
   * Fatture tab because a deal's header is where its verbs live -- and it opens the
   * dialog with the customer, the deal and the first line already answered.
   */
  describe('the «Nuova fattura» action', () => {
    async function openDeal() {
      mockGet.mockImplementation(
        ((path: string) => {
          if (path === '/api/deals/{deal_id}') return ok(DEAL)
          // `useStages` unwraps to a bare array, not to a page.
          if (path === '/api/pipeline-stages') return ok([])
          return ok({ items: [], next_cursor: null })
        }) as never,
      )
      renderWithClient(<DealDetail />)
      await screen.findByRole('tab', { name: 'Panoramica' })
    }

    it('opens a proforma already filled in from the deal', async () => {
      auth.canWrite = true
      await openDeal()

      const button = await screen.findByRole('button', { name: 'Nuova fattura' })
      // Before «Modifica»: creating is the thing this header is most often opened for.
      const actions = screen.getAllByRole('button').map((element) => element.textContent)
      expect(actions.indexOf('Nuova fattura')).toBeLessThan(actions.indexOf('Modifica'))

      await userEvent.click(button)
      expect(await screen.findByRole('dialog')).toBeInTheDocument()
      // Neither picker: this dialog was opened from the record that answers both.
      expect(screen.queryByLabelText(/^Cliente/)).not.toBeInTheDocument()
      expect(screen.queryByLabelText(/^Deal/)).not.toBeInTheDocument()
      expect(screen.getByLabelText('Descrizione riga 1')).toHaveValue('Sito vetrina')
      expect(screen.getByLabelText('Prezzo unitario riga 1')).toHaveValue('4500.00')
      // Both parties named out of the deal this page has already read: no second
      // request, and no «…» to watch resolve. `DealCustomerCard`'s own `useCustomer`
      // is no help here -- it lives in the Collegamenti tab, still unmounted.
      expect(screen.getByText('ACME Srl')).toBeInTheDocument()
      expect(mockGet).not.toHaveBeenCalledWith('/api/customers/{customer_id}', expect.anything())
    })

    it('is not offered to a reader', async () => {
      await openDeal()
      expect(screen.queryByRole('button', { name: 'Nuova fattura' })).not.toBeInTheDocument()
    })
  })
})
