import { createFileRoute, redirect } from '@tanstack/react-router'

// Mirrors routes/index.tsx's own bare "/" -> "/app" redirect: the tabbed layout
// (routes/app/impostazioni.tsx) has no content of its own to show for the bare
// "/app/impostazioni" path (typed directly, or reached via a stale link), so
// this sends it to the first tab rather than leaving `<Outlet />` empty there.
export const Route = createFileRoute('/app/impostazioni/')({
  beforeLoad: () => {
    throw redirect({ to: '/app/impostazioni/campi' })
  },
})
