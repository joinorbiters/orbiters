import { createFileRoute } from '@tanstack/react-router'

// Placeholder so the admin-only AppShell nav item (required, and typed-router-checked)
// has a real destination -- the custom-field-definitions admin screen is a later slice.
function CampiPersonalizzatiPage() {
  return (
    <div className="p-8">
      <h1 className="text-2xl font-semibold">Impostazioni</h1>
      <p className="mt-2 text-muted-foreground">
        La gestione dei campi personalizzati arriva in un prossimo slice.
      </p>
    </div>
  )
}

export const Route = createFileRoute('/app/impostazioni/campi')({
  component: CampiPersonalizzatiPage,
})
