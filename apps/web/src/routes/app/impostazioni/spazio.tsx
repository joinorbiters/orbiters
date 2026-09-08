import { createFileRoute } from '@tanstack/react-router'
import { SpacePanel } from '@/features/settings/SpacePanel'

export const Route = createFileRoute('/app/impostazioni/spazio')({ component: SpacePanel })
