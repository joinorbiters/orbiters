import { createFileRoute } from '@tanstack/react-router'
import { GetStartedPage } from '@/features/get-started/GetStartedPage'

export const Route = createFileRoute('/app/get-started')({ component: GetStartedPage })
