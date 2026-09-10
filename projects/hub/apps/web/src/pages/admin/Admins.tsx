import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ApiError, admin, type AdminCreate } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { Empty, Header } from './lists'

const ADMINS_KEY = ['admins'] as const
/** Mirrors `PASSWORD_MIN_LENGTH` in `orbiters_core.admin`; the API is the one that refuses. */
const PASSWORD_MIN_LENGTH = 10

const EMPTY: AdminCreate = { nome: '', email: '', password: '' }

/**
 * Who reads this area, and the form that adds one more (ORB-123). The creating admin
 * chooses the password and hands it over out of band, as `orbiters createadmin` does on
 * the server; the rules (one address, ten characters) are the service's, and a 422
 * comes back naming the field, so the form points at it rather than blaming everything.
 * No deactivation and no deletion here, on purpose.
 */
export function AdminAdmins() {
  const client = useQueryClient()
  const list = useQuery({ queryKey: ADMINS_KEY, queryFn: () => admin.admins() })
  const [draft, setDraft] = useState<AdminCreate>(EMPTY)
  const [created, setCreated] = useState<string | null>(null)
  const create = useMutation({
    mutationFn: (data: AdminCreate) => admin.createAdmin(data),
    onSuccess: (made) => {
      setDraft(EMPTY)
      setCreated(made.email)
      void client.invalidateQueries({ queryKey: ADMINS_KEY })
    },
  })

  const failure = create.error instanceof ApiError ? create.error : null
  const message = failure
    ? failure.message
    : create.error
      ? 'Non riesco a creare l’amministratore.'
      : null
  const wrong = (field: keyof AdminCreate) => failure?.fields.includes(field) || undefined

  function submit(event: FormEvent) {
    event.preventDefault()
    setCreated(null)
    create.mutate({ ...draft, nome: draft.nome.trim(), email: draft.email.trim() })
  }

  function field(name: keyof AdminCreate) {
    return (value: string) => setDraft((current) => ({ ...current, [name]: value }))
  }

  return (
    <>
      <Header title="Amministratori" count={list.data?.length} />

      {list.isError ? (
        <Empty>Non riesco a leggere la lista.</Empty>
      ) : list.isPending ? (
        <Empty>Caricamento…</Empty>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr className="border-b">
              <th className="px-6 py-2 font-medium">Chi</th>
              <th className="px-3 py-2 font-medium">Stato</th>
              <th className="px-6 py-2 text-right font-medium">Da quando</th>
            </tr>
          </thead>
          <tbody>
            {list.data.map((row) => (
              <tr key={row.id} className="border-b last:border-0 hover:bg-muted">
                <td className="px-6 py-2.5">
                  <p className="font-medium">{row.nome}</p>
                  <p className="text-xs text-muted-foreground">{row.email}</p>
                </td>
                <td className="px-3 py-2.5">
                  <Badge variant="pill">{row.attivo ? 'Attivo' : 'Disattivato'}</Badge>
                </td>
                <td className="px-6 py-2.5 text-right text-muted-foreground">{formatDate(row.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <section aria-labelledby="nuovo-admin" className="border-t px-6 py-6">
        <h2 id="nuovo-admin" className="text-sm font-medium">
          Nuovo amministratore
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Scegli tu la password, almeno {PASSWORD_MIN_LENGTH} caratteri, e comunicala a voce o su un
          canale sicuro: qui non viene inviata nessuna email.
        </p>
        <form onSubmit={submit} className="mt-4 grid max-w-2xl gap-4 sm:grid-cols-3">
          <div className="space-y-2">
            <Label htmlFor="admin-nome">Nome</Label>
            <Input
              id="admin-nome"
              required
              maxLength={120}
              autoComplete="off"
              value={draft.nome}
              onChange={(event) => field('nome')(event.target.value)}
              aria-invalid={wrong('nome')}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="admin-email">Email</Label>
            <Input
              id="admin-email"
              type="email"
              required
              autoComplete="off"
              value={draft.email}
              onChange={(event) => field('email')(event.target.value)}
              aria-invalid={wrong('email')}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="admin-password">Password</Label>
            <Input
              id="admin-password"
              type="password"
              required
              minLength={PASSWORD_MIN_LENGTH}
              autoComplete="new-password"
              value={draft.password}
              onChange={(event) => field('password')(event.target.value)}
              aria-invalid={wrong('password')}
            />
          </div>
          {message && (
            <p role="alert" className="text-sm text-destructive sm:col-span-3">
              {message}
            </p>
          )}
          {created && !create.isPending && !create.error && (
            <p role="status" className="text-sm sm:col-span-3">
              Amministratore creato: <span className="font-medium">{created}</span>. Ora può accedere
              con la password che gli hai dato.
            </p>
          )}
          <div className="sm:col-span-3">
            <Button type="submit" size="sm" disabled={create.isPending}>
              {create.isPending ? 'Creo…' : 'Crea amministratore'}
            </Button>
          </div>
        </form>
      </section>
    </>
  )
}
