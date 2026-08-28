import { createFileRoute } from '@tanstack/react-router'
import { MarginsTable } from '@/features/analytics/MarginsTable'

export const Route = createFileRoute('/app/analisi/margini')({ component: MarginsTable })
