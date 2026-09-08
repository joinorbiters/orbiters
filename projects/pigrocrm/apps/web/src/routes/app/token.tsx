import { createFileRoute } from '@tanstack/react-router'
import { TokensPanel } from '@/features/tokens/TokensPanel'

// A top-level sibling of clienti/persone/deal, deliberately *not* nested under
// impostazioni/: `PatService` scopes tokens by `actor.id`, not role (any
// authenticated user manages their own), so this route carries no admin guard
// -- see features/tokens/queries.ts's own docstring on `useTokens`.
export const Route = createFileRoute('/app/token')({ component: TokensPanel })
