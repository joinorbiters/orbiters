import { Link } from '@tanstack/react-router'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Skeleton } from '@/components/ui/skeleton'
import { BigNumber } from './charts'
import { hours, money, percent } from './format'
import { Freshness } from './Freshness'
import type { Periodo } from './periodo'
import { useEconomicDashboard } from './queries'

/**
 * §5. **No new aggregate exists on this page**: every figure is a field of the response,
 * and every one of them was produced by `AnalyticsService` or by `InvoiceRepository`. The
 * formatters in `./format` change how a string looks and never what it says.
 *
 * Four presentation rules this file exists to honour, each with a test:
 *  - the revenue label is "Fatturato (imponibile, emesso)" in full, never "Fatturato";
 *  - the margin is two columns, closed and in progress, with **no** box holding their sum;
 *  - "Scaduto" is a subset rendered *inside* the "Da incassare" card, not a second addable
 *    line;
 *  - the fiscal estimate is a **link**, not a number.
 *
 * The three blocks are deliberately separate elements with `data-block` / `data-testid`
 * hooks, because their separation is the point rather than a layout preference. A
 * receivable is money owed with VAT in it; revenue is `imponibile`; accrued value is
 * neither. §5.2 says they never share a total row, and the tests assert on the containment
 * rather than on the copy so that no rearrangement can quietly put them in one.
 */

export function EconomicTab({ periodo }: { periodo: Periodo }) {
  const query = useEconomicDashboard(periodo)

  // The error branch comes first, and not by accident: on a failure `isPending` is false
  // while `data` is still undefined, so a single `isPending || !data` guard would answer a
  // failed read with a spinner that never resolves. No table, no cards, no freshness stamp
  // -- an empty dashboard drawn after a failure says "there is nothing" when the truth is
  // "I do not know". Rendered from the query's own `error`, never from component state: an
  // error copied into state and not cleared is a defect this codebase has fixed twice.
  if (query.isError) return <QueryErrorBanner error={query.error} />
  if (query.isPending || !query.data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  const data = query.data
  const pnl = data.pnl
  const rows = [
    // The full label, not "Fatturato" (§5.1). The three extra words are what stop this
    // figure and the "Valore vinto nel periodo" of the commercial tab -- and the
    // receivable below -- being read as the same thing.
    {
      label: 'Fatturato (imponibile, emesso)',
      closed: money(pnl.chiusi.ricavi),
      running: money(pnl.in_corso.ricavi),
    },
    {
      label: 'Costi diretti',
      closed: money(pnl.chiusi.costi_diretti),
      running: money(pnl.in_corso.costi_diretti),
    },
    {
      label: 'Costo del lavoro',
      closed: money(pnl.chiusi.costo_lavoro),
      running: money(pnl.in_corso.costo_lavoro),
    },
    {
      label: 'Margine lordo',
      closed: money(pnl.chiusi.margine_lordo),
      running: money(pnl.in_corso.margine_lordo),
    },
    {
      label: 'Margine %',
      closed: percent(pnl.chiusi.margine_percentuale),
      running: percent(pnl.in_corso.margine_percentuale),
    },
  ]

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          {/* Slice 4 §6.4: whether the period can still move belongs beside the total, not
              in a footnote. A closed period says so too -- the same sentence with the
              opposite fact, so its absence is never what carries the meaning. */}
          {pnl.periodo_chiuso ? 'Periodo chiuso' : 'Periodo non chiuso'}
          {pnl.voci_scritte_in_ritardo > 0 &&
            ` · ${pnl.voci_scritte_in_ritardo} voci scritte in ritardo`}
          {!pnl.periodo_chiuso && ' — questi numeri possono ancora muoversi.'}
        </p>
        <Freshness calcolatoAlle={data.calcolato_alle} onRefresh={() => void query.refetch()} />
      </div>

      <div className="overflow-x-auto rounded-lg border bg-card p-4" data-block="pnl">
        <table className="w-full text-sm">
          <caption className="mb-2 text-left text-sm font-medium">
            Conto economico del periodo — la <strong>cifra riportabile</strong> è la colonna
            «Deal chiusi». Le due colonne non si sommano.
          </caption>
          <thead>
            <tr className="text-left text-muted-foreground">
              <th scope="col" className="font-normal">
                Voce
              </th>
              <th scope="col" className="font-normal">
                Deal chiusi
              </th>
              <th scope="col" className="font-normal">
                Deal in corso
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label}>
                <th scope="row" className="py-1 pr-3 text-left font-normal">
                  {row.label}
                </th>
                <td className="py-1 tabular-nums">{row.closed}</td>
                <td className="py-1 tabular-nums text-muted-foreground">{row.running}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-3 text-xs text-muted-foreground">
          {/* Slice 4 §7.1: overhead is never apportioned onto a deal, so it is stated on its
              own rather than folded into either column's costs. */}
          Spese generali del periodo: <strong>{money(pnl.spese_generali)}</strong> — non
          ripartite su nessun deal.
        </p>
      </div>

      <section data-testid="maturato" className="rounded-lg border bg-card p-4">
        {/* §5: "sotto un'intestazione diversa da «ricavi»". The scope -- «nel periodo» --
            is in the heading, because the same three quantities appear without a period on
            the operational tab, and a reader who cannot see which is which will add them. */}
        <h2 className="text-sm font-medium">Maturato e non fatturato — nel periodo</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Non sono ricavi e non entrano in nessun margine.
        </p>
        <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-muted-foreground">Valore maturato non fatturato</dt>
            <dd className="tabular-nums">{money(pnl.valore_maturato)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Ore fatturabili non fatturate</dt>
            <dd className="tabular-nums">{hours(pnl.ore_fatturabili_non_fatturate)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Ore senza tariffa</dt>
            {/* Counted, never valued: an hour with no rate is not an hour worth zero, and
                a total alone could not tell the two apart. */}
            <dd className="tabular-nums">{pnl.ore_senza_tariffa}</dd>
          </div>
        </dl>
      </section>

      <div className="grid gap-4 sm:grid-cols-3">
        <div data-testid="da-incassare" className="rounded-lg border bg-card p-4">
          <p className="text-sm text-muted-foreground">Da incassare</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{money(data.da_incassare)}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Totale con IVA. È un credito, non un ricavo: non entra in nessun margine.
          </p>
          {/* A subset, rendered inside its parent card and marked as one -- never a second
              addable line (§5.2). The `data-subset-of` attribute is what the test asserts
              on, so the relationship survives a restyling that moves the border. */}
          <p
            data-testid="scaduto"
            data-subset-of="da-incassare"
            className="mt-2 border-l-2 pl-3 text-sm text-muted-foreground"
          >
            di cui scaduto: <strong className="tabular-nums">{money(data.scaduto)}</strong>
          </p>
        </div>
        <BigNumber
          label="Fatture emesse nel periodo"
          value={`${data.fatture_emesse}`}
          hint="conteggio, non un importo"
        />
        <div className="rounded-lg border bg-card p-4">
          <p className="text-sm text-muted-foreground">Stima fiscale</p>
          <p className="mt-1 text-sm">
            {/* §5.3: a link, never a number. A dashboard is the screen most likely to end
                up in a screenshot or a screen share, and the estimate is admin-only. */}
            <Link to="/app/analisi/fiscale" className="underline underline-offset-2">
              Apri la stima fiscale
            </Link>
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Non è mostrata qui: una dashboard è la schermata che più facilmente finisce in uno
            screenshot.
          </p>
        </div>
      </div>
    </div>
  )
}
