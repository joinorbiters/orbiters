import { createFileRoute, redirect } from '@tanstack/react-router'

// Mirrors `routes/app/impostazioni/index.tsx`: the tabbed layout has no content of its
// own for the bare "/app/analisi" path (typed directly, or reached from a stale link),
// so this sends it to the first tab rather than leaving `<Outlet />` empty there.
export const Route = createFileRoute('/app/analisi/')({
  beforeLoad: () => {
    throw redirect({ to: '/app/analisi/margini' })
  },
})
