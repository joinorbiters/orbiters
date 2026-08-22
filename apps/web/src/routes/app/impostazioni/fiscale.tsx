import { createFileRoute } from '@tanstack/react-router'
import { FiscalPanel } from '@/features/settings/FiscalPanel'

export const Route = createFileRoute('/app/impostazioni/fiscale')({ component: FiscalPanel })
