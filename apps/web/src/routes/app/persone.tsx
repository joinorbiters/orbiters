import { createFileRoute } from '@tanstack/react-router'

// Placeholder so the AppShell nav item (required, and typed-router-checked) has a
// real destination -- the full Persone list/detail views are a later slice.
function PersonePage() {
  return (
    <div className="p-8">
      <h1 className="text-2xl font-semibold">Persone</h1>
      <p className="mt-2 text-muted-foreground">
        L'elenco persone arriva in un prossimo slice.
      </p>
    </div>
  )
}

export const Route = createFileRoute('/app/persone')({ component: PersonePage })
