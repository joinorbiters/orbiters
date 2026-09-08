import { useState } from 'react'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { PeriodPicker } from './PeriodPicker'
import { PeriodTotals } from './PnlRows'
import { currentMonthPeriod, type Period } from './period'
import { usePeriodPnl } from './queries'

/**
 * Margini: the period P&L, in the two columns the backend returns and no others.
 *
 * There is no per-deal list here, and that is not an omission: `GET /api/analytics/pnl`
 * returns totals, not rows, and the per-deal breakdown is the other tab
 * (`/analisi/preventivo-consuntivo`, served by `GET /api/analytics/budget`). Building a
 * deal list here from a second endpoint would put two answers to the same question on
 * one screen, with nothing keeping them in agreement.
 */
export function MarginsTable() {
  const [period, setPeriod] = useState<Period>(currentMonthPeriod)
  const pnl = usePeriodPnl(period)

  return (
    <div className="space-y-4">
      <PeriodPicker value={period} onChange={setPeriod} />

      {pnl.isError && <QueryErrorBanner error={pnl.error} />}
      {!pnl.isError && (pnl.isLoading || !pnl.data) && <Skeleton className="h-64 w-full" />}

      {!pnl.isError && pnl.data && (
        <>
          <div className="flex items-center gap-3">
            {/* Which of the two a report is, before any number is read off it: a closed
                period's hours can no longer be edited, so its figures have stopped
                moving. An open one's have not. */}
            <Badge variant={pnl.data.periodo_chiuso ? 'default' : 'secondary'}>
              {pnl.data.periodo_chiuso ? 'periodo chiuso' : 'periodo aperto'}
            </Badge>
            {pnl.data.voci_scritte_in_ritardo > 0 && (
              // Hours written after the window ended are why the same report, re-read
              // next week, can disagree with itself. Shown so that difference is
              // expected rather than discovered.
              <p className="text-xs text-muted-foreground">
                {pnl.data.voci_scritte_in_ritardo} voci scritte dopo la fine del periodo:
                questo numero può ancora muoversi.
              </p>
            )}
          </div>

          <PeriodTotals pnl={pnl.data} />
        </>
      )}
    </div>
  )
}
