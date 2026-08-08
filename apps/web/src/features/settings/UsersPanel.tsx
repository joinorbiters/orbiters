import type { ColumnDef } from '@tanstack/react-table'
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DataTable, type DataTableFeatures } from '@/components/DataTable'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { fieldErrorFrom, toProblem, type ProblemDetail } from '@/lib/api'
import { useCreateUser, useUpdateUser, useUsers, type UserRecord } from './queries'

const ROLES: { value: UserRecord['ruolo']; label: string }[] = [
  { value: 'admin', label: 'Amministratore' },
  { value: 'collaboratore', label: 'Collaboratore' },
  { value: 'readonly', label: 'Sola lettura' },
]

const KNOWN_FIELDS = ['email', 'password', 'nome', 'ruolo']

function unattributed(problem: ProblemDetail | null): string | null {
  if (!problem) return null
  const fieldError = fieldErrorFrom(problem)
  if (fieldError && KNOWN_FIELDS.includes(fieldError.field)) return null
  return problem.detail
}

export function UsersPanel() {
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [nome, setNome] = useState('')
  const [password, setPassword] = useState('')
  const [ruolo, setRuolo] = useState<UserRecord['ruolo']>('collaboratore')
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  const users = useUsers()
  const create = useCreateUser()
  const toggleActive = useUpdateUser()

  const fieldError = problem ? fieldErrorFrom(problem) : null
  const banner = unattributed(problem)

  function openDialog() {
    setProblem(null)
    setEmail('')
    setNome('')
    setPassword('')
    setRuolo('collaboratore')
    setOpen(true)
  }

  function submit() {
    setProblem(null)
    create.mutate(
      { email, nome, password, ruolo },
      {
        onSuccess: () => {
          toast.success('Utente creato')
          setOpen(false)
        },
        onError: (error) => setProblem(toProblem(error)),
      },
    )
  }

  const columns: ColumnDef<DataTableFeatures, UserRecord>[] = [
    { header: 'Nome', accessorKey: 'nome' },
    { header: 'Email', accessorKey: 'email' },
    {
      header: 'Ruolo',
      id: 'ruolo',
      accessorFn: (row) => ROLES.find((role) => role.value === row.ruolo)?.label ?? row.ruolo,
    },
    {
      header: 'Stato',
      id: 'attivo',
      cell: (info) => (
        <Badge variant={info.row.original.attivo ? 'default' : 'secondary'}>
          {info.row.original.attivo ? 'Attivo' : 'Disattivato'}
        </Badge>
      ),
    },
    {
      header: '',
      id: 'actions',
      cell: (info) => {
        const user = info.row.original
        return (
          <Button
            variant="ghost"
            size="sm"
            disabled={toggleActive.isPending}
            onClick={() =>
              toggleActive.mutate(
                { userId: user.id, body: { attivo: !user.attivo } },
                {
                  onSuccess: () =>
                    toast.success(user.attivo ? 'Utente disattivato' : 'Utente riattivato'),
                  onError: (error) => toast.error(toProblem(error).detail),
                },
              )
            }
          >
            {user.attivo ? 'Disattiva' : 'Riattiva'}
          </Button>
        )
      },
    },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-semibold">Utenti</h2>
          <p className="text-sm text-muted-foreground">
            Non esiste registrazione pubblica: gli utenti li crei tu. Il cambio password non è
            disponibile in questa versione — disattiva e ricrea l&apos;utente se serve.
          </p>
        </div>
        <Button onClick={openDialog}>
          <Plus className="mr-2 size-4" />
          Nuovo utente
        </Button>
      </div>

      <DataTable
        columns={columns}
        data={users.data ?? []}
        isLoading={users.isLoading}
        isError={users.isError}
        error={users.error}
        emptyMessage="Nessun utente."
      />

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nuovo utente</DialogTitle>
            <DialogDescription>
              La password deve avere almeno 10 caratteri. Comunicala tu all&apos;utente: il sistema
              non invia email in questa versione.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            {banner && (
              <p
                role="alert"
                className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                {banner}
              </p>
            )}
            <div className="space-y-2">
              <Label htmlFor="user-nome">Nome</Label>
              <Input
                id="user-nome"
                aria-invalid={fieldError?.field === 'nome'}
                value={nome}
                onChange={(event) => setNome(event.target.value)}
              />
              {fieldError?.field === 'nome' && (
                <p className="text-sm text-destructive">{fieldError.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="user-email">Email</Label>
              <Input
                id="user-email"
                type="email"
                aria-invalid={fieldError?.field === 'email'}
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
              {fieldError?.field === 'email' && (
                <p className="text-sm text-destructive">{fieldError.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="user-password">Password</Label>
              <Input
                id="user-password"
                type="password"
                aria-invalid={fieldError?.field === 'password'}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
              {fieldError?.field === 'password' && (
                <p className="text-sm text-destructive">{fieldError.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="user-ruolo">Ruolo</Label>
              <Select value={ruolo} onValueChange={(value) => setRuolo(value as typeof ruolo)}>
                <SelectTrigger id="user-ruolo" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ROLES.map((role) => (
                    <SelectItem key={role.value} value={role.value}>
                      {role.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Annulla
            </Button>
            <Button onClick={submit} disabled={create.isPending}>
              {create.isPending ? 'Creazione…' : 'Crea'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
