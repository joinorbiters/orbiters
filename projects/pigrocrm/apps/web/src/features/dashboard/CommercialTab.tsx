import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Skeleton } from '@/components/ui/skeleton'
import { BarRows, BigNumber, type BarRow } from './charts'
import { money, percent } from './format'
import { Freshness } from './Freshness'
import type { Periodo } from './periodo'
import { useCommercialDashboard } from './queries'

/**
 * Since 2026-09-08 the commercial tab is the first row and the pipeline: what closed in
 * the period (won, lost, conversion, value) and what is open by stage. The detail
 * table, the pending offers, the 30-day forecast and the signals left the page; the API
 * still returns them for the agent.
 */
export function CommercialTab({ periodo }: { periodo: Periodo }) {
  const query = useCommercialDashboard(periodo)

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
  const widest = data.pipeline.reduce((best, row) => (row.numero > best ? row.numero : best), 0)
  const bars: BarRow[] = data.pipeline.map((row, index) => ({
    label: row.stage_nome,
    value: `${row.numero}`,
    ratio: widest === 0 ? 0 : row.numero / widest,
    tone: index + 1,
  }))

  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <Freshness calcolatoAlle={data.calcolato_alle} onRefresh={() => void query.refetch()} />
      </div>

      {/* Three across (design spec §4), not four: the KPI card is wider now that its
          value is 30px, and the fourth card of a four-up row was the one that wrapped
          first on a laptop anyway. */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
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
          hint="valore dichiarato dai deal, non fatturato"
        />
      </div>

      <BarRows caption="Pipeline aperta per stato" rows={bars} />

      {data.chiusure_non_attribuibili > 0 && (
        <p className="text-xs text-muted-foreground">
          {data.chiusure_non_attribuibili} deal chiusi prima dell&apos;introduzione di questa
          misura <strong>non sono attribuibili</strong> a un periodo e non entrano nelle cifre
          sopra.
        </p>
      )}
    </div>
  )
}
