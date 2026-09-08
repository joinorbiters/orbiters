import { createFileRoute } from '@tanstack/react-router'
import { TemplatesPanel } from '@/features/settings/TemplatesPanel'

export const Route = createFileRoute('/app/impostazioni/template')({ component: TemplatesPanel })
