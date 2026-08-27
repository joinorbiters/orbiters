import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useEffect, useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { toProblem } from '@/lib/api'
import { useAuth } from '@/lib/auth'

function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)

  /**
   * The redirect is driven by the *session*, never by "the login call returned".
   *
   * `await login(...); await navigate({ to: '/app' })` -- what this was -- looks
   * equivalent and is not. `AuthProvider.login` publishes the new user by writing it
   * into react-query's cache, and react-query delivers that write to its subscribers
   * through `notifyManager`, which batches onto a later microtask. So the navigation
   * issued on the very next line runs a render of `/app`'s layout (`routes/app.tsx`)
   * in which `useAuth().user` is still `null` -- and that layout's own
   * "unauthenticated visitors go to the login page" effect immediately pushes back to
   * /app/login. Confirmed live, deterministically, on this machine: `history` recorded
   * exactly `push /app` followed by `push /app/login`, with a 200 from
   * `POST /api/auth/login` and both session cookies set, so a correct login landed the
   * user back on the login form and `e2e/auth.spec.ts`'s third test failed on «Ciao
   * E2E» with no other symptom. Waiting for `user` to actually be non-null removes the
   * race by construction rather than by ordering luck.
   *
   * It also gives an already-authenticated visitor who lands on /app/login the same
   * treatment, which is the behaviour that screen should have had anyway: the login
   * form is not a page a live session has any use for.
   */
  useEffect(() => {
    if (user) void navigate({ to: '/app' })
  }, [user, navigate])

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      await login(email, password)
    } catch (error) {
      // The API deliberately does not say whether it was the email or the password.
      toast.error(toProblem(error).detail)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-2xl">
            Pigro<span className="text-[var(--color-watermelon)]">CRM</span>
          </CardTitle>
          <CardDescription>Il CRM che lavora al posto tuo.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                required
                autoComplete="username"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? 'Accesso in corso…' : 'Accedi'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}

export const Route = createFileRoute('/app/login')({ component: LoginPage })
