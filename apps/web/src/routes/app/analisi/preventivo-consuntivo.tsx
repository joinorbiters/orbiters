import { createFileRoute } from '@tanstack/react-router'
import { BudgetTable } from '@/features/analytics/BudgetTable'

export const Route = createFileRoute('/app/analisi/preventivo-consuntivo')({
  component: BudgetTable,
})
