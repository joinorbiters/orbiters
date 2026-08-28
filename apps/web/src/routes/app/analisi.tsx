import { createFileRoute } from '@tanstack/react-router'
import { AnalyticsLayout } from '@/features/analytics/AnalyticsLayout'

// Only `Route` is exported: anything else opts this route out of the router plugin's
// automatic code-splitting. The layout itself lives in `features/analytics/`.
export const Route = createFileRoute('/app/analisi')({ component: AnalyticsLayout })
