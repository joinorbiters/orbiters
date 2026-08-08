import { createFileRoute } from '@tanstack/react-router'
import { UsersPanel } from '@/features/settings/UsersPanel'

export const Route = createFileRoute('/app/impostazioni/utenti')({ component: UsersPanel })
