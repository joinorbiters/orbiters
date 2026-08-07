import { createFileRoute } from '@tanstack/react-router'

// Placeholder so the AppShell nav item (required, and typed-router-checked) has a
// real destination -- the full Deal pipeline/board is a later slice.
function DealPage() {
  return (
    <div className="p-8">
      <h1 className="text-2xl font-semibold">Deal</h1>
      <p className="mt-2 text-muted-foreground">La pipeline deal arriva in un prossimo slice.</p>
    </div>
  )
}

export const Route = createFileRoute('/app/deal')({ component: DealPage })
