import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Skeleton } from '@/components/ui/skeleton'
import { BarRows, BigNumber, type BarRow } from './charts'
import { Freshness } from './Freshness'
import type { Periodo } from './periodo'
import { useCommercialDashboard } from './queries'

/**
 * §4. Pipeline snapshot plus two period measures. Touches no invoice and no hour, which is
 * what lets it ship before slice 3.
 *
 * **Nothing here computes anything.** Every money string comes from the API already
 * decided; the only derived quantity is a bar's `ratio`, and it is derived from the
 * *count* of deals -- an integer the server sent, compared with other integers the server
 * sent -- never from a money value. `src/test/no-browser-arithmetic.test.ts` is what keeps
 * that true.
 *
 * Two figures the brief asked for are deliberately absent, because the response cannot
 * support either honestly:
 *
 *  - a *pipeline-wide* "valore ponderato". `PipelineStageSummary.valore_ponderato` is per
 *    stage and there is no total in the response; rendering the first stage's figure under
 *    a total's label would print one stage's estimate as the pipeline's, and summing the
 *    stages here would be a money total born in the browser. The estimates are shown per
 *    stage instead, in their own column with their own heading (§4).
 *  - a "deal senza valore" total, for the same reason in miniature: `senza_valore` is per
 *    stage, and a browser-side sum is a figure born here. Per stage is also the more
 *    useful answer -- it says *where* the gaps are.
 */

const euro = new Intl.NumberFormat('it-IT', {
  style: 'currency',
  currency: 'EUR',
  // Mandatory: it-IT's default withholds the thousands separator until the integer part
  // has five digits, so 1500.00 would print as "1500,00 €".
  useGrouping: 'always',
})

function money(value: string): string {
  // The API's decimal string goes into the formatter verbatim. Never `Number(value)`:
  // `Number("0.29") * 100` is 28.999999999999996, and a currency formatter fed a float is
  // how cents disappear. `Intl.NumberFormat.format` accepts a string and parses it with
  // full decimal precision (ES2023.Intl, which this project's tsconfig already declares
  // for `useGrouping: 'always'`).
  //
  // The cast is to `Intl.StringNumericLiteral` -- the template-literal type that signature
  // actually takes, `\`${number}\` | "Infinity" | ...` -- and not to `number`, which would
  // be a lie about what is passed. A `Numeric(12, 2)` column always arrives in that shape.
  return euro.format(value as Intl.StringNumericLiteral)
}

function percent(value: string | null | undefined): string {
  // A dash, not "0,00%": zero per cent means "I lost everything", no closed deals means
  // something else entirely (§4, and slice 4 §7.1's identical rule for the margin).
  // `?? null` is not enough: the field is optional in the generated type, so `undefined`
  // is reachable and must mean the same thing as `null` -- nothing closed.
  if (value === null || value === undefined) return '—'
  return `${value.replace('.', ',')}%`
}

export function CommercialTab({ periodo }: { periodo: Periodo }) {
  const query = useCommercialDashboard(periodo)

  // The error branch comes first, and not by accident: on a failure `isPending` is false
  // while `data` is still undefined, so a single `isPending || !data` guard would answer a
  // failed read with a spinner that never resolves. No table, no cards, no "nessun dato" --
  // an empty dashboard drawn after a failure says "there is nothing" when the truth is
  // "I do not know" (§8.6's rule, applied here).
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
  // The widest count in the pipeline, used only to scale the bars: a maximum over integers
  // the server sent, not a total of anything.
  const widest = data.pipeline.reduce((best, row) => (row.numero > best ? row.numero : best), 0)
  const bars: BarRow[] = data.pipeline.map((row, index) => ({
    label: row.stage_nome,
    // The bar's length and the number beside it are the same measure -- a count. The money
    // is in the table below, where it cannot be misread as the thing the bar encodes.
    value: `${row.numero}`,
    ratio: widest === 0 ? 0 : row.numero / widest,
    tone: index + 1,
  }))

  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <Freshness calcolatoAlle={data.calcolato_alle} onRefresh={() => void query.refetch()} />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <BigNumber label="Deal vinti nel periodo" value={`${data.chiusure.vinti}`} />
        <BigNumber label="Deal persi nel periodo" value={`${data.chiusure.persi}`} />
        <BigNumber
          label="Tasso di conversione"
          value={percent(data.chiusure.tasso_conversione)}
          hint="vinti su vinti + persi"
        />
        <BigNumber
          label="Valore vinto nel periodo"
          value={money(data.chiusure.valore_vinto)}
          // §4: it is what the deal *claimed*, not what was invoiced. The two figures live
          // on two pages for this reason, and the hint says so where it cannot be missed.
          hint="valore dichiarato dai deal, non fatturato"
        />
      </div>

      <BarRows caption="Pipeline aperta per stato" rows={bars} />

      {data.pipeline.length > 0 && (
        <section className="overflow-x-auto rounded-lg border bg-card p-4">
          <table className="w-full text-sm">
            <caption className="mb-2 text-left text-sm font-medium">Dettaglio per stato</caption>
            <thead>
              <tr className="text-left text-muted-foreground">
                <th scope="col" className="py-1 pr-3 font-normal">
                  Stato
                </th>
                <th scope="col" className="py-1 pr-3 font-normal">
                  Valore aperto
                </th>
                {/* §4: the weighted value gets a heading of its own, different from any
                    revenue figure, and the word «stima» is in the heading rather than in a
                    footnote nobody reads. */}
                <th scope="col" className="py-1 pr-3 font-normal">
                  Valore ponderato (stima)
                </th>
                <th scope="col" className="py-1 font-normal">
                  Deal senza valore
                </th>
              </tr>
            </thead>
            <tbody>
              {data.pipeline.map((row) => (
                <tr key={row.stage_id}>
                  <th scope="row" className="py-1 pr-3 text-left font-normal">
                    {row.stage_nome}
                  </th>
                  <td className="py-1 pr-3 tabular-nums">{money(row.valore_totale)}</td>
                  <td className="py-1 pr-3 tabular-nums">{money(row.valore_ponderato)}</td>
                  {/* Counted, never summed as zero: a deal with no expected value is not a
                      deal worth nothing, and a total alone cannot tell the two apart. */}
                  <td className="py-1 tabular-nums">{row.senza_valore}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-muted-foreground">
            Il valore ponderato è una stima: valore previsto × probabilità dello stato. Non è
            fatturato e non va sommato ai ricavi.
          </p>
        </section>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <BigNumber
          label="Chiusure previste (30 giorni)"
          value={`${data.chiusure_previste_30_giorni}`}
        />
        <BigNumber
          label="Offerte inviate in attesa"
          value={`${data.offerte_in_attesa_totale}`}
          tone="accent"
        />
      </div>

      <section className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium">Offerte in attesa di risposta</h2>
        {data.offerte_in_attesa.length === 0 ? (
          <p className="mt-2 text-sm text-muted-foreground">Nessuna offerta in attesa.</p>
        ) : (
          <ul className="mt-2 space-y-1 text-sm">
            {data.offerte_in_attesa.map((offer) => (
              <li key={offer.document_id} className="flex justify-between gap-4">
                <span className="truncate">{offer.titolo}</span>
                <span className="shrink-0 text-muted-foreground">
                  {/* `null` days means `stato_dal` is unknown; "0 giorni" would read as
                      "sent today", which is a different fact. */}
                  {offer.giorni === null ? 'data ignota' : `${offer.giorni} giorni`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium">Segnali</h2>
        {/* Stated, not linked. The brief pointed this at
            `/app/documenti?solo_deal_non_vinto=true`; there is no `/app/documenti` list
            route in this codebase -- only `/app/documenti/$documentId` -- and no list page
            anywhere reads a search parameter, so the link would have landed on a 404 under
            a label promising a filtered list. That is the defect Task A13 found in its own
            brief. The drill-through belongs with the document list when one exists. */}
        <p className="mt-2 text-sm">
          Offerta accettata, deal non vinto: <strong>{data.offerte_accettate_deal_non_vinto}</strong>
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          È il caso in cui l&apos;automazione «offerta accettata → deal vinto» non è scattata.
          Le esecuzioni e le mancate esecuzioni, con il motivo di ciascuna, sono in
          Impostazioni → Automazioni.
        </p>
        {data.chiusure_non_attribuibili > 0 && (
          <p className="mt-3 text-xs text-muted-foreground">
            {data.chiusure_non_attribuibili} deal chiusi prima dell&apos;introduzione di questa
            misura <strong>non sono attribuibili</strong> a un periodo e non entrano nelle cifre
            sopra.
          </p>
        )}
      </section>
    </div>
  )
}
