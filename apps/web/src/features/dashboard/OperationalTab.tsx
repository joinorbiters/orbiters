import { Link } from '@tanstack/react-router'
import { formatOccurredAt, labelForEntityType, labelForKind } from '@/components/activityLabels'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Skeleton } from '@/components/ui/skeleton'
import { formatIsoDayMonth, formatIsoWeekday } from '@/lib/dates'
import { HOURS_SCALE, scaledFromDecimalString } from '@/lib/decimal'
import { Sparkline, type SparkPoint } from './charts'
import { hours, money } from './format'
import { Freshness } from './Freshness'
import { useOperationalDashboard, type Signal } from './queries'

/**
 * §6. One question: what do I have to do now. **No period, and no props** -- the current
 * week and a backlog are the two things that make no sense in the past, and
 * `OperationalTab.length === 0` is asserted so that a period cannot be added later without
 * somebody deciding to.
 *
 * The days without hours are not a statistic: they are the real failure slice 4 §13 names
 * when it refuses a stopwatch -- "I never entered Tuesday". So they are **named**, not
 * counted, and a day logged with `0.00` hours is not among them: somebody who entered a
 * zero made a statement about that day, and the server is what draws that distinction
 * (`giorni_senza_ore` is its own list, not the days whose `ore` happen to be zero).
 *
 * Which is also why the sparkline's columns are labelled by *weekday* and not by date: a
 * date under every column would put "17/03" on screen for a day that was logged as zero,
 * and the one thing this tab must never do is make that day look like a day nobody filled
 * in. The dates appear exactly once, in the list of the days actually missing.
 *
 * **No figure is computed here.** The one derived quantity is the sparkline's `ratio`, and
 * it goes through `lib/decimal.ts`'s `scaledFromDecimalString` -- the module whose own
 * docstring names hours as the one thing the browser may do arithmetic on, and which turns
 * `"8.00"` into the integer `800` by splitting the string rather than by parsing a float.
 * Nothing on screen comes out of it: it decides how tall a decorative line is drawn, and
 * the table beneath carries the values as the strings the API sent.
 */

/**
 * The drill-through for a signal, as a typed route rather than as the `collegamento`
 * string.
 *
 * `signal.collegamento` is the same destination and this component's tests assert the two
 * agree -- but an `<a href>` built from a server string is a full document navigation out
 * of the SPA, and this codebase has no such link anywhere. `<Link>` also makes the
 * destination checked by `tsc` against the route's own `validateSearch`, so a filter that
 * the target list does not read cannot be linked to at all.
 *
 * A signal whose `codice` this build does not know renders as **text**. Guessing a route
 * for it would produce either a 404 or -- quieter and worse -- an unfiltered list under a
 * label promising a filtered one, which is criterion 2's failure in the form nobody
 * notices. The same judgement `CommercialTab.tsx` recorded for its own signal.
 */
function SignalLabel({ signal }: { signal: Signal }) {
  const className = 'underline underline-offset-2'
  switch (signal.codice) {
    case 'fatturato_non_vinto':
      return (
        <Link to="/app/deal/lista" search={{ fatturato_non_vinto: true }} className={className}>
          {signal.etichetta}
        </Link>
      )
    case 'vinto_da_fatturare':
      return (
        <Link to="/app/deal/lista" search={{ da_fatturare: true }} className={className}>
          {signal.etichetta}
        </Link>
      )
    case 'scaduto_non_incassato':
      return (
        <Link to="/app/fatture" search={{ scadute: true }} className={className}>
          {signal.etichetta}
        </Link>
      )
    default:
      return <>{signal.etichetta}</>
  }
}

export function OperationalTab() {
  const query = useOperationalDashboard()

  // The error branch comes first, and not by accident: on a failure `isPending` is false
  // while `data` is still undefined, so a single `isPending || !data` guard would answer a
  // failed read with a spinner that never resolves. Rendered from the query's own `error`,
  // never copied into component state, so a later success clears it by construction.
  if (query.isError) return <QueryErrorBanner error={query.error} />
  if (query.isPending || !query.data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  const data = query.data
  const week = data.settimana
  // The tallest day of the week, in hundredths of an hour, used only to scale the line.
  // A maximum over the week, never a sum: this page adds nothing up.
  const tallest = week.giorni.reduce(
    (best, day) => Math.max(best, scaledFromDecimalString(day.ore, HOURS_SCALE)),
    0,
  )
  const points: SparkPoint[] = week.giorni.map((day) => ({
    label: formatIsoWeekday(day.giorno),
    // The string the API sent, with the decimal comma Italian reads. Not `hours()`: seven
    // repetitions of the word "ore" in a seven-column table is noise, and the caption
    // already says what the row is.
    value: day.ore.replace('.', ','),
    ratio: tallest === 0 ? 0 : scaledFromDecimalString(day.ore, HOURS_SCALE) / tallest,
  }))

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          Settimana {formatIsoDayMonth(week.da)}–{formatIsoDayMonth(week.a)} ·{' '}
          <strong>{hours(week.ore_totali)}</strong> in totale
        </p>
        <Freshness calcolatoAlle={data.calcolato_alle} onRefresh={() => void query.refetch()} />
      </div>

      <Sparkline caption="Ore per giorno — settimana corrente" points={points} />

      <section className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium">
          {week.giorni_senza_ore.length === 0
            ? 'Settimana completa: nessun giorno scoperto'
            : `${week.giorni_senza_ore.length} giorni senza ore`}
        </h2>
        {week.giorni_senza_ore.length > 0 && (
          <>
            <ul data-testid="giorni-senza-ore" className="mt-2 flex flex-wrap gap-2 text-sm">
              {week.giorni_senza_ore.map((day) => (
                <li key={day} className="rounded border px-2 py-0.5 tabular-nums">
                  {formatIsoDayMonth(day)}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-muted-foreground">
              Un giorno registrato con zero ore non è fra questi: zero è un valore, non
              un&apos;assenza.
            </p>
          </>
        )}
      </section>

      <section data-testid="arretrato" className="rounded-lg border bg-card p-4">
        {/* §6.3: the scope is in the heading. The economic tab shows the same three
            quantities *for a period*, and a reader who cannot see which is which will
            subtract one from the other. */}
        <h2 className="text-sm font-medium">Arretrato da fatturare — in totale</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Senza periodo: «quanto ho da fatturare» non è una domanda su un mese. {data.arretrato.voci}{' '}
          voci in tutto.
        </p>
        <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-muted-foreground">Ore fatturabili non fatturate</dt>
            <dd className="tabular-nums">{hours(data.arretrato.ore_fatturabili_non_fatturate)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Valore maturato</dt>
            <dd className="tabular-nums">{money(data.arretrato.valore_maturato)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Voci senza tariffa</dt>
            {/* Counted, never valued: an hour with no rate is not an hour worth zero, and
                a value alone could not tell the two apart. */}
            <dd className="tabular-nums">{data.arretrato.voci_senza_tariffa}</dd>
          </div>
        </dl>
      </section>

      <section className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium">Segnali di incoerenza</h2>
        <ul className="mt-2 space-y-1 text-sm">
          {data.segnali.map((signal) => (
            <li key={signal.codice}>
              <SignalLabel signal={signal} />:{' '}
              <strong className="tabular-nums">{signal.conteggio}</strong>
            </li>
          ))}
        </ul>
        {/* §6.2: "Il conteggio non manda niente." There is deliberately no action here --
            a count beside a list of overdue customers is exactly where a "sollecita tutti"
            button gets added by somebody who did not read the spec. */}
        <p className="mt-2 text-xs text-muted-foreground">
          Sono conteggi: aprono un elenco, non inviano niente.
        </p>
      </section>

      <section data-testid="attivita-recenti" className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium">Attività recenti</h2>
        {data.attivita_recenti.length === 0 ? (
          <p className="mt-2 text-sm text-muted-foreground">Nessuna attività recente.</p>
        ) : (
          <ul className="mt-2 space-y-1 text-sm">
            {/* The same words the entity timeline uses, from the same table
                (`components/activityLabels.ts`) -- two screens naming one event two
                different ways is the small version of the problem this slice is about. */}
            {data.attivita_recenti.map((activity) => (
              <li key={activity.id} className="flex flex-wrap justify-between gap-2">
                <span>
                  {labelForKind(activity.kind)} · {labelForEntityType(activity.entity_type)}
                </span>
                <span className="text-muted-foreground">
                  {formatOccurredAt(activity.occurred_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
