import { Outlet, useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'
import { useMember } from '@/lib/member'

/** Nothing under /io renders until the session is known; without one the visitor goes
 *  to /accedi. The shape of `AdminLayout`'s guard, without the frame. */
export function MemberGuard() {
  const me = useMember()
  const navigate = useNavigate()

  useEffect(() => {
    if (!me.isPending && me.data === null) void navigate({ to: '/accedi', replace: true })
  }, [me.isPending, me.data, navigate])

  if (me.isPending) return <p className="text-sm text-muted-foreground">Caricamento…</p>
  if (!me.data) return null
  return <Outlet />
}
