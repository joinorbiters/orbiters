import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
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
 * Who reads this area, and a button that adds one more (ORB-123, ORB-125). The page is
 * the list; the form lives in a dialog behind «Nuovo amministratore», so the list reads
 * as a list. The creating admin chooses the password and hands it over out of band, as
 * `orbiters createadmin` does on the server; the rules (one address, ten characters) are
 * the service's, and a 422 comes back naming the field, so the dialog stays open and
 * points at it rather than blaming everything. On success it closes, the list refreshes
 * and the page says who was created. No deactivation and no deletion here, on purpose.
 */
export function AdminAdmins() {
  const client = useQueryClient()
  const list = useQuery({ queryKey: ADMINS_KEY, queryFn: () => admin.admins() })
  const [open, setOpen] = useState(false)
  const [created, setCreated] = useState<string | null>(null)
  const [draft, setDraft] = useState<AdminCreate>(EMPTY)
  const create = useMutation({
    mutationFn: (data: AdminCreate) => admin.createAdmin(data),
    onSuccess: (made) => {
      setOpen(false)
      setCreated(made.email)
      void client.invalidateQueries({ queryKey: ADMINS_KEY })
    },
  })

  /** Every opening starts clean: an empty draft and no error from the last attempt. While
   *  a request is out the dialog stays: closing it would swallow a late refusal, and a
   *  late success would close whatever dialog had been reopened in the meantime, since
   *  the mutation's `onSuccess` outlives `reset()`. */
  function toggle(next: boolean) {
    if (!next && create.isPending) return
    if (next) {
      setDraft(EMPTY)
      create.reset()
    }
    setOpen(next)
  }

  const failure = create.error instanceof ApiError ? create.error : null
  const message = failure
    ? failure.message
    : create.error
      ? 'Non riesco a creare l’amministratore.'
      : null
  const wrong = (field: keyof AdminCreate) => failure?.fields.includes(field) || undefined

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate({ ...draft, nome: draft.nome.trim(), email: draft.email.trim() })
  }

  function field(name: keyof AdminCreate) {
    return (value: string) => setDraft((current) => ({ ...current, [name]: value }))
  }

  return (
    <Dialog open={open} onOpenChange={toggle}>
      <Header title="Amministratori" count={list.data?.length}>
        {/* A Radix trigger rather than a plain button, so focus comes back here on close. */}
        <DialogTrigger asChild>
          <Button type="button" size="sm">
            <Plus data-icon="inline-start" />
            Nuovo amministratore
          </Button>
        </DialogTrigger>
      </Header>

      {/* Always mounted: a live region that appears already filled is often not read out. */}
      <p role="status" aria-live="polite" className={created ? 'border-b px-6 py-3 text-sm' : undefined}>
        {created && (
          <>
            Amministratore creato: <span className="font-medium">{created}</span>. Ora può accedere con
            la password che gli hai dato.
          </>
        )}
      </p>

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

      <DialogContent>
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Nuovo amministratore</DialogTitle>
            <DialogDescription>
              Scegli tu la password, almeno {PASSWORD_MIN_LENGTH} caratteri, e comunicala a voce o su un
              canale sicuro: qui non viene inviata nessuna email.
            </DialogDescription>
          </DialogHeader>
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
            <p role="alert" className="text-sm text-destructive">
              {message}
            </p>
          )}
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline" disabled={create.isPending}>
                Annulla
              </Button>
            </DialogClose>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? 'Creo…' : 'Crea amministratore'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
