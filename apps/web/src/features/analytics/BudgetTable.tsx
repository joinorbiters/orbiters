import { useState } from 'react'
import { DataTable } from '@/components/DataTable'
import { formatMoneyValue } from '@/features/time/columns'
import { PeriodPicker } from './PeriodPicker'
import { buildBudgetColumns } from './columns'
import { currentMonthPeriod, type Period } from './period'
import { useBudget } from './queries'

/**
 * Preventivo/consuntivo: one row per deal active in the window, the estimate beside what
 * actually happened.
 *
 * The list is paginated from the first commit and the period filter is mandatory, both
 * decided on the backend: a margins view is by its nature a list of deals, so unbounded
 * growth would otherwise become invisible here first.
 */
export function BudgetTable() {
  const [period, setPeriod] = useState<Period>(currentMonthPeriod)
  const budget = useBudget(period)
  const page = budget.data

  return (
    <div className="space-y-4">
      <PeriodPicker value={period} onChange={setPeriod} />

      <DataTable
        columns={buildBudgetColumns()}
        data={page?.items ?? []}
        isLoading={budget.isLoading}
        isError={budget.isError}
        error={budget.error}
        emptyMessage="Nessun deal con attività in questo periodo."
      />

      {page && (
        <div className="space-y-1 text-xs text-muted-foreground">
          <p>
            Totale preventivato {formatMoneyValue(page.totale_preventivato)} · totale
            fatturato {formatMoneyValue(page.totale_ricavi)} su {page.deal_preventivati} deal
            con preventivo.
          </p>
          {/* Counted, not hidden: a deal nobody estimated contributes revenue to the
              total above and nothing to the budget, so the two are not comparable
              without knowing how many deals are in that state. */}
          {page.deal_non_preventivati > 0 && (
            <p>
              {page.deal_non_preventivati} deal senza preventivo: presenti in questo elenco,
              esclusi dal totale preventivato.
            </p>
          )}
          {/* The backend pages this list, so a wide window can genuinely return a partial
              answer. Saying so beats a table that quietly stops. */}
          {page.next_cursor !== null && (
            <p>Elenco troncato: restringi il periodo per vedere i deal rimanenti.</p>
          )}
        </div>
      )}
    </div>
  )
}
