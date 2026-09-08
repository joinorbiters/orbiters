import { createFileRoute } from '@tanstack/react-router'
import { SollecitiPage } from '@/features/solleciti/SollecitiPage'

// Only `Route` is exported: a route file exporting anything else opts that route out of
// the router plugin's automatic code-splitting, which `routeTree.gen.ts` warns about.
//
// No admin guard. `SollecitiService.candidates` is a plain read of the register and is
// deliberately not role-gated -- seeing which invoices are late is reading your own
// books -- and the write behind «Prepara sollecito» is gated at the service, which is
// where the refusal belongs: a route guard here would hide the list from a `readonly`
// user who is allowed to see it.
export const Route = createFileRoute('/app/solleciti')({ component: SollecitiPage })
