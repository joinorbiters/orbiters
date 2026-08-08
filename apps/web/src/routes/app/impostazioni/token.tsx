import { createFileRoute } from '@tanstack/react-router'
import { TokensPanel } from '@/features/settings/TokensPanel'

export const Route = createFileRoute('/app/impostazioni/token')({ component: TokensPanel })
