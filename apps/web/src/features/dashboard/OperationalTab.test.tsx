/**
 * §6's tab. Its two most important assertions are the ones about days with no hours: they
 * are **named**, and a day logged with zero hours is not among them.
 *
 * `vi.mock('@/lib/api')` and not a stubbed `globalThis.fetch`: `api` is an openapi-fetch
 * client built at import time, so replacing `fetch` afterwards changes nothing. `msw` is
 * not a dependency of this project.
 *
 * The `Link` mock renders the `to` and `search` this component chose as a real `href`, and
 * every link assertion below is written against the `collegamento` string the *server*
 * sent. That is what keeps the two halves of criterion 2 honest: the card's count and the
 * list behind it are one predicate on the server, and this file fails if the tab ever
 * navigates somewhere the server did not name.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { OperationalTab } from './OperationalTab'
import { api } from '@/lib/api'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { GET: vi.fn(), POST: vi.fn(), PUT: vi.fn(), DELETE: vi.fn() } }
})

vi.mock('@tanstack/react-router', () => ({
  Link: ({
    to,
    search,
    children,
    ...rest
  }: {
    to: string
    search?: Record<string, unknown>
    children: React.ReactNode
  } & Record<string, unknown>) => {
    const query = new URLSearchParams(
      Object.entries(search ?? {}).map(([key, value]) => [key, String(value)]),
    ).toString()
    return (
      <a href={query ? `${to}?${query}` : to} {...rest}>
        {children}
      </a>
    )
  },
}))

function ok(data: unknown) {
  return { data, response: new Response(null, { status: 200 }) } as never
}

function failed(error: unknown, status: number) {
  return { error, response: new Response(null, { status }) } as never
}

const SEGNALI = [
  {
    codice: 'fatturato_non_vinto',
    etichetta: 'Fatturato ma non vinto',
    conteggio: 2,
    collegamento: '/app/deal/lista?fatturato_non_vinto=true',
  },
  {
    codice: 'vinto_da_fatturare',
    etichetta: 'Vinto ma da fatturare',
    conteggio: 5,
    collegamento: '/app/deal/lista?da_fatturare=true',
  },
  {
    codice: 'scaduto_non_incassato',
    etichetta: 'Scaduto e non incassato',
    conteggio: 1,
    collegamento: '/app/fatture?scadute=true',
  },
]

const RESPONSE = {
  calcolato_alle: '2026-03-18T10:00:00Z',
  settimana: {
    da: '2026-03-16',
    a: '2026-03-22',
    giorni: [
      { giorno: '2026-03-16', ore: '8.00' },
      // Logged, and logged as zero. Somebody made a statement about this day, so it is not
      // one of the missing ones below.
      { giorno: '2026-03-17', ore: '0.00' },
      { giorno: '2026-03-18', ore: '4.00' },
      { giorno: '2026-03-19', ore: '0.00' },
      { giorno: '2026-03-20', ore: '0.00' },
      { giorno: '2026-03-21', ore: '0.00' },
      { giorno: '2026-03-22', ore: '0.00' },
    ],
    giorni_senza_ore: ['2026-03-19', '2026-03-20', '2026-03-21', '2026-03-22'],
    ore_totali: '12.00',
  },
  arretrato: {
    ore_fatturabili_non_fatturate: '90.00',
    valore_maturato: '4500.00',
    voci_senza_tariffa: 3,
    voci: 22,
  },
  segnali: SEGNALI,
  attivita_recenti: [
    {
      id: '0192f3b2-8c1a-7c3d-9f4e-1a2b3c4d5e6f',
      entity_type: 'deal',
      entity_id: '0192f3b2-8c1a-7c3d-9f4e-1a2b3c4d5e70',
      kind: 'stage_changed',
      actor_id: null,
      actor_type: 'system',
      payload: {},
      occurred_at: '2026-03-18T09:30:00Z',
    },
  ],
}

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <OperationalTab />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(api.GET).mockReset()
})

describe('OperationalTab', () => {
  it('takes no period prop at all', () => {
    // §6: the current week and a backlog are the two things that make no sense in the past.
    expect(OperationalTab.length).toBe(0)
  })

  it('requests the endpoint without a period', async () => {
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    await screen.findByRole('table', { name: /ore per giorno/i })
    expect(api.GET).toHaveBeenCalledWith('/api/dashboard/operativa')
    // Not merely "the first call had no period": no call at all carries one, so a period
    // cannot be smuggled in through a second request.
    for (const call of vi.mocked(api.GET).mock.calls) {
      expect(JSON.stringify(call)).not.toContain('"da"')
    }
  })

  it('shows the week as a sparkline with its equivalent table', async () => {
    // A chart without a table is a figure a screen reader does not read (§13). The svg is
    // decoration layered on top, and says so.
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    const table = await screen.findByRole('table', { name: /ore per giorno/i })
    expect(screen.getByTestId('sparkline-svg')).toHaveAttribute('aria-hidden', 'true')
    // The hours themselves, as the strings the API sent, decimal comma and all.
    expect(within(table).getByText('8,00')).toBeInTheDocument()
    expect(within(table).getByText('4,00')).toBeInTheDocument()
  })

  it('names the days with no hours', async () => {
    // The real failure slice 4 §13 names when it refuses a stopwatch. Naming the days is
    // what makes the figure actionable rather than a statistic.
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByText(/4 giorni senza ore/i)).toBeInTheDocument()
    const missing = screen.getByTestId('giorni-senza-ore')
    for (const day of ['19/03', '20/03', '21/03', '22/03']) {
      expect(within(missing).getByText(day)).toBeInTheDocument()
    }
  })

  it('does not count a day logged with zero hours as missing', async () => {
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    await screen.findByText(/4 giorni senza ore/i)
    // 2026-03-17 has 0.00 hours and is NOT in `giorni_senza_ore`: somebody who entered a
    // zero made a statement about that day. The whole document is searched, not only the
    // list, so a second rendering of it anywhere would fail here too -- which is why the
    // sparkline's columns are labelled by weekday and not by date.
    expect(screen.queryByText('17/03')).not.toBeInTheDocument()
  })

  it('says the week is covered rather than listing nothing', async () => {
    // The negative of the assertion above. Without it "N giorni senza ore" could be a
    // constant heading over an empty list and no test would notice.
    vi.mocked(api.GET).mockResolvedValue(
      ok({ ...RESPONSE, settimana: { ...RESPONSE.settimana, giorni_senza_ore: [] } }),
    )
    renderTab()
    expect(await screen.findByText(/nessun giorno scoperto/i)).toBeInTheDocument()
    expect(screen.queryByTestId('giorni-senza-ore')).not.toBeInTheDocument()
  })

  it('labels the backlog as a total, not as a period figure', async () => {
    // §5's rule: the label carries the scope, and the two figures are never side by side.
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    const backlog = await screen.findByTestId('arretrato')
    expect(backlog).toHaveTextContent(/in totale/i)
    expect(backlog).toHaveTextContent('4.500,00 €')
    expect(backlog).toHaveTextContent('90,00 ore')
  })

  it('shows the hours without a rate as a figure of their own', async () => {
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    expect(await screen.findByText(/senza tariffa/i)).toBeInTheDocument()
    // Counted, never valued: an hour with no rate is not an hour worth zero.
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.queryByText('0,00 €')).not.toBeInTheDocument()
  })

  it('renders each signal as a link to exactly the list the server named', async () => {
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    await screen.findByText(/segnali di incoerenza/i)
    for (const signal of SEGNALI) {
      const link = screen.getByRole('link', { name: new RegExp(signal.etichetta, 'i') })
      // The destination this component chose, compared with the one the API sent. A card
      // and its drill-through are the same predicate (§7's criterion 2); if the two ever
      // disagree, one of them is describing rows the other does not.
      expect(link).toHaveAttribute('href', signal.collegamento)
    }
    expect(screen.getByText('5')).toBeInTheDocument()
  })

  it('states a signal it has no route for instead of linking nowhere', async () => {
    // A future fourth signal. A link built from a code this build does not know would be
    // either a 404 or -- worse -- an unfiltered list under a label promising a filtered
    // one, which is the same defect in a quieter form.
    vi.mocked(api.GET).mockResolvedValue(
      ok({
        ...RESPONSE,
        segnali: [
          {
            codice: 'segnale_futuro',
            etichetta: 'Segnale futuro',
            conteggio: 7,
            collegamento: '/app/qualcosa?filtro=true',
          },
        ],
      }),
    )
    renderTab()
    expect(await screen.findByText(/segnale futuro/i)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /segnale futuro/i })).not.toBeInTheDocument()
  })

  it('offers no way to send anything from a signal', async () => {
    // §6.2: "Il conteggio **non** manda niente." A count next to a list of overdue
    // customers is exactly where somebody later adds a "send all" button.
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    await screen.findByText(/scaduto e non incassato/i)
    expect(screen.queryByRole('button', { name: /sollecit/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /invia/i })).not.toBeInTheDocument()
  })

  it('shows the recent activities in the words the timeline uses', async () => {
    vi.mocked(api.GET).mockResolvedValue(ok(RESPONSE))
    renderTab()
    const recent = await screen.findByTestId('attivita-recenti')
    expect(recent).toHaveTextContent(/cambio stato/i)
    expect(recent).toHaveTextContent(/deal/i)
  })

  it('says there is no recent activity rather than drawing an empty list', async () => {
    vi.mocked(api.GET).mockResolvedValue(ok({ ...RESPONSE, attivita_recenti: [] }))
    renderTab()
    expect(await screen.findByText(/nessuna attività recente/i)).toBeInTheDocument()
  })

  it('renders an error banner and no figures when the request fails', async () => {
    vi.mocked(api.GET).mockResolvedValue(
      failed({ title: 'Errore', detail: 'Non disponibile', code: 'unavailable' }, 500),
    )
    renderTab()
    expect(await screen.findByRole('alert')).toHaveTextContent('Non disponibile')
    // The error branch is checked *before* the loading branch: on a failure `isPending` is
    // false while `data` is still undefined, so a single `isPending || !data` guard answers
    // a failed read with a spinner that never resolves.
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByText(/giorni senza ore/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/nessuna attività recente/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/aggiornato/i)).not.toBeInTheDocument()
  })
})
