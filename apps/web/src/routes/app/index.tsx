import { createFileRoute } from '@tanstack/react-router'
import { useAuth } from '@/lib/auth'

function Dashboard() {
  const { user } = useAuth()
  return (
    <div className="p-8">
      <h1 className="text-2xl font-semibold">Ciao {user?.nome}</h1>
      <p className="mt-2 text-muted-foreground">
        La dashboard con i grafici arriva nello slice 6. Per ora usa il menu a sinistra.
      </p>
    </div>
  )
}

export const Route = createFileRoute('/app/')({ component: Dashboard })
