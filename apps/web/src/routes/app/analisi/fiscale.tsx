import { createFileRoute } from '@tanstack/react-router'
import { FiscalPanel } from '@/features/analytics/FiscalPanel'

export const Route = createFileRoute('/app/analisi/fiscale')({ component: FiscalPanel })
