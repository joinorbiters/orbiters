import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useMemo, useState } from 'react'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Button } from '@/components/ui/button'
import { useDeals } from '@/features/deals/queries'
import { useAuth } from '@/lib/auth'
import { formatHoursValue } from './columns'
import { useTimeEntries } from './queries'
import { WeekGridRow } from './WeekGridRow'
import { buildGrid, columnTotal, gridTotal, shiftWeek, weekDays } from './week'

/**
 * The screen that attacks the real failure mode. §13 argues it explicitly: the way a
 * freelancer's time tracking fails is not "I forgot to stop the timer", it is **"I never
 * entered Tuesday"**. A stopwatch needs a live-session entity, a recovery story for the
 * closed browser and another for the second device -- three mechanisms -- and does
 * nothing about Tuesday. A grid where a whole week is visibly incomplete does.
 */
export function WeekGrid() {
  const { user } = useAuth()
  const userId = user?.id
  const [anchor, setAnchor] = useState(() => new Date())
  const days = useMemo(() => weekDays(anchor), [anchor])

  const entries = useTimeEntries(
    { user_id: userId, da: days[0]?.iso, a: days[6]?.iso },
    // See `useTimeEntries`' own docstring: an unfiltered list is answered, for an admin,
    // with the whole team's hours, so this must not fire before the session is known.
    { enabled: userId !== undefined },
  )
  const deals = useDeals()

  const grid = useMemo(() => buildGrid(entries.data?.items ?? [], days), [entries.data, days])
  const dealNames = useMemo(
    () => new Map((deals.data?.items ?? []).map((deal) => [deal.id, deal.nome])),
    [deals.data],
  )
  // Rows: every deal with an entry this week, plus every deal that exists, so a week can
  // be started from nothing rather than only continued. Deduplicated by id; ordered by
  // name through `localeCompare(..., 'it')`, so the row a person is looking for is where
  // the alphabet says it is and does not move when an hour is logged.
  const rows = useMemo(() => {
    const ids = new Set<string>([...grid.keys()])
    for (const deal of deals.data?.items ?? []) ids.add(deal.id)
    return [...ids].sort((left, right) =>
      (dealNames.get(left) ?? '').localeCompare(dealNames.get(right) ?? '', 'it'),
    )
  }, [grid, deals.data, dealNames])

  const header = (
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Ore</h1>
        <p className="text-muted-foreground">
          {days[0]?.label} — {days[6]?.label}
        </p>
      </div>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="icon"
          aria-label="Settimana precedente"
          onClick={() => setAnchor((current) => shiftWeek(current, -1))}
        >
          <ChevronLeft className="size-4" />
        </Button>
        <Button variant="outline" onClick={() => setAnchor(new Date())}>
          Questa settimana
        </Button>
        <Button
          variant="outline"
          size="icon"
          aria-label="Settimana successiva"
          onClick={() => setAnchor((current) => shiftWeek(current, 1))}
        >
          <ChevronRight className="size-4" />
        </Button>
      </div>
    </header>
  )

  // A failed request is neither "loading" nor "there is nothing here", and rendering a
  // grid of empty cells for it would say the second -- a week with no hours in it, which
  // is exactly the claim this screen is built to make loudly. The banner instead, and no
  // grid at all: see `QueryErrorBanner`'s own docstring.
  if (entries.isError || deals.isError) {
    return (
      <div className="space-y-4 p-8">
        {header}
        <QueryErrorBanner error={entries.error ?? deals.error} />
      </div>
    )
  }

  // Same distinction on the other side: an empty grid drawn while the week is still in
  // flight would be indistinguishable from a week nobody worked.
  if (userId === undefined || entries.isPending || deals.isPending) {
    return (
      <div className="space-y-4 p-8">
        {header}
        <p className="text-sm text-muted-foreground">Caricamento…</p>
      </div>
    )
  }

  return (
    <div className="space-y-4 p-8">
      {header}

      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b bg-muted/40">
              <th scope="col" className="p-2 text-left font-medium">
                Deal
              </th>
              {days.map((day) => (
                <th key={day.iso} scope="col" className="p-2 text-center font-medium">
                  {/* The weekday abbreviation alone repeats every week; the day number
                      under it is what tells somebody which week they are looking at
                      without reading back up to the header. */}
                  <span className="block">{day.short}</span>
                  <span className="block text-xs text-muted-foreground">{day.iso.slice(8)}</span>
                </th>
              ))}
              <th scope="col" className="p-2 text-right font-medium">
                Totale
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={9} className="p-4 text-center text-muted-foreground">
                  Nessun deal: creane uno per registrare le ore.
                </td>
              </tr>
            ) : (
              rows.map((dealId) => (
                <WeekGridRow
                  key={dealId}
                  dealId={dealId}
                  dealName={dealNames.get(dealId) ?? dealId}
                  userId={userId}
                  days={days}
                  row={grid.get(dealId)}
                />
              ))
            )}
          </tbody>
          <tfoot>
            <tr className="border-t bg-muted/40 font-medium">
              <th scope="row" className="p-2 text-left">
                Totale
              </th>
              {days.map((day) => (
                <td
                  key={day.iso}
                  data-testid={`column-total-${day.iso}`}
                  className="p-2 text-center tabular-nums"
                >
                  {formatHoursValue(columnTotal(grid, day.iso))}
                </td>
              ))}
              <td data-testid="grid-total" className="p-2 text-right tabular-nums">
                {formatHoursValue(gridTotal(grid))}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>

      <p className="text-xs text-muted-foreground">
        La tariffa viene congelata sulla voce quando la registri. Una cella con più voci
        nello stesso giorno mostra la prima: l&apos;elenco completo è nella tab «Ore» del
        deal.
      </p>
    </div>
  )
}
