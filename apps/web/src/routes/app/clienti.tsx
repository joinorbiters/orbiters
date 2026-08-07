import { createFileRoute } from '@tanstack/react-router'

// Placeholder so the AppShell nav item (required, and typed-router-checked) has a
// real destination -- the full Clienti list/detail views are a later slice.
function ClientiPage() {
  return (
    <div className="p-8">
      <h1 className="text-2xl font-semibold">Clienti</h1>
      <p className="mt-2 text-muted-foreground">
        L'elenco clienti arriva in un prossimo slice.
      </p>
    </div>
  )
}

export const Route = createFileRoute('/app/clienti')({ component: ClientiPage })
