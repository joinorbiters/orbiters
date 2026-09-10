import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useEffect, useRef } from 'react'
import { useEnter } from '@/lib/member'

/** Where the mail's link lands. The token is posted from here, once, and never fetched
 *  by the link itself: a scanner that opens every link in a message does not run this
 *  page, so it cannot spend the token. */
export function Entra() {
  const { t } = useSearch({ strict: false }) as { t?: string }
  const navigate = useNavigate()
  const enter = useEnter()
  const started = useRef(false)

  useEffect(() => {
    if (started.current || !t) return
    started.current = true
    enter.mutate(t, { onSuccess: () => void navigate({ to: '/io', replace: true }) })
  }, [t, enter, navigate])

  if (!t || enter.isError) {
    return (
      <div className="mx-auto max-w-xl space-y-4 text-center">
        <h1 className="text-3xl font-semibold tracking-tight">Questo link non funziona</h1>
        <p role="alert" className="text-muted-foreground">
          Il link non è più valido: vale quindici minuti e una volta sola.
        </p>
        <Link to="/accedi" className="text-sm underline underline-offset-2">
          Chiedine un altro
        </Link>
      </div>
    )
  }
  return <p className="text-center text-sm text-muted-foreground">Un attimo, ti facciamo entrare…</p>
}
