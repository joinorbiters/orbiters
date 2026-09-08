import type { ColumnDef } from '@tanstack/react-table'
import type { DataTableFeatures } from '@/components/DataTable'
import { formatHoursValue, formatMoneyValue } from '@/features/time/columns'
import { formatPercent } from './format'
import type { BudgetVsActualRow } from './queries'

const EMPTY = '—'
const NOT_BUDGETED = 'non preventivato'
const NO_PRO_RATA = 'pro-rata non calcolabile'

/**
 * The estimate-versus-actual row, as columns.
 *
 * Every cell is a string the API sent, formatted; nothing here divides one figure by
 * another. The two flags the backend carries -- `non_preventivato` and
 * `pro_rata_non_calcolabile` -- exist precisely so the browser does not have to infer
 * "why is this null?" from the null itself, and they are read here rather than guessed.
 */
export function buildBudgetColumns(): ColumnDef<DataTableFeatures, BudgetVsActualRow>[] {
  return [
    { header: 'Deal', accessorKey: 'nome' },
    {
      header: 'Ore prev. / cons.',
      id: 'ore',
      accessorFn: (row) =>
        `${formatHoursValue(row.ore_preventivate)} / ${formatHoursValue(row.ore_consuntivate)}`,
    },
    {
      header: 'Avanzamento',
      id: 'avanzamento_ore',
      // `null` is "not comparable", never "0%": a deal nobody estimated has not done
      // nothing, and a row reading 0% would say exactly that.
      accessorFn: (row) =>
        row.non_preventivato ? NOT_BUDGETED : formatPercent(row.avanzamento_ore),
    },
    {
      header: 'Preventivo pieno',
      id: 'valore_preventivato',
      // Shown BESIDE the pro-rata, never instead of it. The full budget answers "what did
      // we sell?", the pro-rata answers "is it on track?", and a report carrying only one
      // of them makes the other question unanswerable.
      accessorFn: (row) => formatMoneyValue(row.valore_preventivato),
    },
    {
      header: 'Preventivo pro-rata',
      id: 'budget_pro_rata',
      accessorFn: (row) =>
        row.pro_rata_non_calcolabile ? NO_PRO_RATA : formatMoneyValue(row.budget_pro_rata),
    },
    { header: 'Fatturato', id: 'ricavi', accessorFn: (row) => formatMoneyValue(row.ricavi) },
    {
      header: 'Scostamento',
      id: 'scostamento_valore',
      accessorFn: (row) =>
        row.scostamento_valore === null ? EMPTY : formatMoneyValue(row.scostamento_valore),
    },
    {
      header: 'Tariffa media prev. / cons.',
      id: 'tariffa_media',
      // The column that serves most: what was realised per hour worked against what was
      // expected. Comparable between deals of very different sizes, and the only form in
      // which "is this client worth it?" has a numeric answer.
      accessorFn: (row) =>
        `${formatMoneyValue(row.tariffa_media_preventivata)} / ${formatMoneyValue(
          row.tariffa_media_consuntivata,
        )}`,
    },
  ]
}
