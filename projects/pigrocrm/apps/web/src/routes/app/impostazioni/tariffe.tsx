import { createFileRoute } from '@tanstack/react-router'
import { RatesPanel } from '@/features/settings/RatesPanel'

export const Route = createFileRoute('/app/impostazioni/tariffe')({ component: RatesPanel })
