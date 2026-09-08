import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useEffect, useState, type FormEvent } from 'react'
import { BrandMark } from '@/components/BrandMark'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api, toProblem, unwrap } from '@/lib/api'
import { slugProblem, slugify, spaceLoginUrl } from '@/lib/tenant'

/** The public host the space will answer on, for the preview under the name field. */
function spaceHost(): string {
  return typeof window === 'undefined' ? '' : window.location.host
}

/** What the server last said about a slug -- tagged with the slug it was said about, so
 *  an answer for the previous name never shows under the current one. */
type Availability =
  | { state: 'idle' }
  | { state: 'checking'; slug: string }
  | { state: 'free'; slug: string }
  | { state: 'taken'; slug: string; reason: string }

export function SignupPage() {
  const navigate = useNavigate()
  const [nome, setNome] = useState('')
  const [slug, setSlug] = useState('')
  const [slugTouched, setSlugTouched] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [availability, setAvailability] = useState<Availability>({ state: 'idle' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [created, setCreated] = useState<string | null>(null)

  // The local grammar check needs no round-trip and no state: a malformed name never
  // leaves the browser.
  const localProblem = slug === '' ? null : slugProblem(slug)

  // Ask the server whether a well-formed address is free, a moment after typing stops.
  // Every setState here happens inside the timer, never synchronously in the effect.
  useEffect(() => {
    if (slug === '' || localProblem) return
    const asked = slug
    const handle = window.setTimeout(() => {
      setAvailability({ state: 'checking', slug: asked })
      void api
        .GET('/api/tenants/{slug}/disponibile', { params: { path: { slug: asked } } })
        .then(({ data }) => {
          if (!data) return
          setAvailability(
            data.disponibile
              ? { state: 'free', slug: asked }
              : { state: 'taken', slug: asked, reason: data.motivo ?? 'questo nome è già in uso' },
          )
        })
        .catch(() => setAvailability({ state: 'idle' }))
    }, 350)
    return () => window.clearTimeout(handle)
  }, [slug, localProblem])

  // The name proposes the address until the person edits the address by hand.
  function onNomeChange(value: string) {
    setNome(value)
    if (!slugTouched) setSlug(slugify(value))
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const tenant = await unwrap(
        api.POST('/api/tenants/', { body: { slug, nome, email, password } }),
      )
      setCreated(tenant.slug)
    } catch (caught) {
      setError(toProblem(caught).detail)
    } finally {
      setBusy(false)
    }
  }

  if (created) {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle className="inline-flex items-center text-2xl">
              <BrandMark className="mr-2.5 size-3.5" />
              Il tuo spazio è pronto
            </CardTitle>
            <CardDescription>
              Risponde su {spaceHost()}/{created}. Entra con l'email e la password che hai
              scelto.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              className="w-full"
              onClick={() => window.location.assign(spaceLoginUrl(created))}
            >
              Vai al login del tuo spazio
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  // Only an answer about *this* slug counts; anything else is still pending.
  const current = availability.state !== 'idle' && availability.slug === slug ? availability : null
  const problem = localProblem ?? (current?.state === 'taken' ? current.reason : null)
  const isFree = current?.state === 'free'
  const canSubmit = !busy && isFree && email !== '' && password !== ''

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="inline-flex items-center text-2xl">
            <BrandMark className="mr-2.5 size-3.5" />
            Crea il tuo spazio
          </CardTitle>
          <CardDescription>
            Un PigroCRM tutto tuo, con i tuoi dati in un database separato.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <div className="space-y-2">
              <Label htmlFor="nome">Il tuo nome</Label>
              <Input
                id="nome"
                autoComplete="name"
                required
                value={nome}
                onChange={(event) => onNomeChange(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="slug">Indirizzo dello spazio</Label>
              <Input
                id="slug"
                autoComplete="off"
                required
                value={slug}
                aria-invalid={problem ? true : undefined}
                aria-describedby="slug-hint"
                onChange={(event) => {
                  setSlugTouched(true)
                  setSlug(event.target.value.toLowerCase())
                }}
              />
              <p id="slug-hint" className="text-muted-foreground text-sm" role="status">
                {problem ??
                  (slug === ''
                    ? 'Lo ricaviamo dal tuo nome, puoi cambiarlo.'
                    : isFree
                      ? `${spaceHost()}/${slug} è libero.`
                      : `${spaceHost()}/${slug} …`)}
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                required
                minLength={10}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
              <p className="text-muted-foreground text-sm">Almeno 10 caratteri.</p>
            </div>
            {error && (
              <p className="text-destructive text-sm" role="alert">
                {error}
              </p>
            )}
            <Button type="submit" className="w-full" disabled={!canSubmit}>
              {busy ? 'Creazione in corso…' : 'Crea lo spazio'}
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="w-full"
              onClick={() => void navigate({ to: '/app/login' })}
            >
              Ho già un account
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}

export const Route = createFileRoute('/app/registrati')({ component: SignupPage })
