import { createFileRoute } from '@tanstack/react-router'
import { EmitterPanel } from '@/features/settings/EmitterPanel'

export const Route = createFileRoute('/app/impostazioni/emittente')({ component: EmitterPanel })
