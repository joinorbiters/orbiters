import type { ColumnDef } from '@tanstack/react-table'
import { Copy, Plus, Trash2 } from 'lucide-react'
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
import { fieldErrorFrom, toProblem, type ProblemDetail } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useCreateToken, useRevokeToken, useTokens, type CreatedToken, type TokenRecord } from './queries'

const ROLE_LABELS: Record<string, string> = {
  admin: 'amministratore',
  collaboratore: 'collaboratore',
  readonly: 'sola lettura',
}

const dateFormatter = new Intl.DateTimeFormat('it-IT', { dateStyle: 'medium', timeStyle: 'short' })

function formatUsed(value: string | null): string {
  return value === null ? 'mai' : dateFormatter.format(new Date(value))
}

export function TokensPanel() {
  const { user } = useAuth()
  const [creating, setCreating] = useState(false)
  const [nome, setNome] = useState('')
  const [problem, setProblem] = useState<ProblemDetail | null>(null)
  const [issued, setIssued] = useState<CreatedToken | null>(null)
  const [copied, setCopied] = useState(false)

  const tokens = useTokens()
  const create = useCreateToken()
  const revoke = useRevokeToken()

  const fieldError = problem ? fieldErrorFrom(problem) : null
  const banner = problem && fieldError?.field !== 'nome' ? problem.detail : null

  function openDialog() {
    setProblem(null)
    setNome('')
    setCreating(true)
  }

  function submit() {
    setProblem(null)
    create.mutate(nome, {
      onSuccess: (created) => {
        // Shown exactly once: PatService stores only a SHA-256 hash of this value
        // (auth/pat_service.py) and has no way to recover or re-display it after
        // this response. `creating`/`nome` are reset here, on success, so the
        // create dialog cannot be reopened with stale state while the reveal
        // dialog below is what actually has the user's attention.
        setIssued(created)
        setCopied(false)
        setCreating(false)
        setNome('')
      },
      onError: (error) => setProblem(toProblem(error)),
    })
  }

  function copyIssued() {
    if (!issued) return
    void navigator.clipboard.writeText(issued.token).then(() => {
      setCopied(true)
      toast.success('Token copiato negli appunti')
    })
  }

  function revokeToken(token: TokenRecord) {
    // No "un-revoke" exists (`PatService` has no such method) -- unlike a field
    // definition's archive/unarchive pair, this really is one-way, so it gets the
    // same confirm guard as an irreversible pipeline-stage delete.
    const confirmed = window.confirm(
      `Revocare il token "${token.nome}"? Chi lo usa smetterà immediatamente di avere accesso. L'operazione non è reversibile.`,
    )
    if (!confirmed) return

    revoke.mutate(token.id, {
      onSuccess: () => toast.success('Token revocato'),
      onError: (error) => toast.error(toProblem(error).detail),
    })
  }

  const columns: ColumnDef<DataTableFeatures, TokenRecord>[] = [
    { header: 'Nome', accessorKey: 'nome' },
    { header: 'Prefisso', id: 'prefix', cell: (info) => <code>{info.row.original.prefix}</code> },
    {
      header: 'Ultimo uso',
      id: 'last_used_at',
      accessorFn: (row) => formatUsed(row.last_used_at),
    },
    {
      header: 'Stato',
      id: 'revoked_at',
      cell: (info) => (
        <Badge variant={info.row.original.revoked_at ? 'secondary' : 'default'}>
          {info.row.original.revoked_at ? 'Revocato' : 'Attivo'}
        </Badge>
      ),
    },
    {
      header: '',
      id: 'actions',
      cell: (info) => {
        const token = info.row.original
        if (token.revoked_at) return null
        return (
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Revoca ${token.nome}`}
            onClick={() => revokeToken(token)}
          >
            <Trash2 className="size-4" />
          </Button>
        )
      },
    },
  ]

  const roleLabel = user ? (ROLE_LABELS[user.ruolo] ?? user.ruolo) : null

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-semibold">Token di accesso</h2>
          <p className="text-sm text-muted-foreground">
            Servono a far usare PigroCRM a un agente (per esempio Claude, tramite il server MCP)
            con le credenziali di questo account. Imposta il token nella variabile
            d&apos;ambiente <code>PIGROCRM_TOKEN</code> di chi lo userà.
          </p>
          <p className="mt-2 text-sm text-muted-foreground">
            Un token eredita <strong>l&apos;intero ruolo di chi lo crea</strong>, senza possibilità
            di limitarne l&apos;ambito e senza scadenza: chiunque lo possieda può fare, tramite
            l&apos;API, tutto ciò che puoi fare tu — un token creato da un amministratore può
            anche creare altri amministratori. Trattalo come una password: non condividerlo e
            revocalo subito se sospetti che sia stato esposto.
          </p>
        </div>
        <Button onClick={openDialog}>
          <Plus className="mr-2 size-4" />
          Nuovo token
        </Button>
      </div>

      <DataTable
        columns={columns}
        data={tokens.data ?? []}
        isLoading={tokens.isLoading}
        isError={tokens.isError}
        error={tokens.error}
        emptyMessage="Nessun token creato."
      />

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nuovo token</DialogTitle>
            <DialogDescription>
              Dai un nome riconoscibile, es. &quot;Claude sul portatile&quot;. Avrà lo stesso ruolo
              di questo account ({roleLabel}) e non scadrà finché non lo revochi.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            {banner && (
              <p
                role="alert"
                className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                {banner}
              </p>
            )}
            <Label htmlFor="token-nome">Nome</Label>
            <Input
              id="token-nome"
              aria-invalid={fieldError?.field === 'nome'}
              value={nome}
              onChange={(event) => setNome(event.target.value)}
            />
            {fieldError?.field === 'nome' && (
              <p className="text-sm text-destructive">{fieldError.message}</p>
            )}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCreating(false)}>
              Annulla
            </Button>
            <Button onClick={submit} disabled={create.isPending}>
              {create.isPending ? 'Creazione…' : 'Crea'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/*
       * The one and only place this value is ever shown. `showCloseButton={false}`
       * plus the two handlers below turn off every way to dismiss this dialog
       * *except* the explicit "Ho copiato il token" button at the bottom -- no
       * Esc, no click-outside, no X icon. `onOpenChange` is a deliberate no-op for
       * the same reason: Radix calls it for all three of those dismissal paths,
       * and the only state change that is allowed to close this dialog is the
       * user's own explicit acknowledgement that the token is gone once they do.
       * A copy button is not enough on its own -- a user who selects and copies
       * the text manually, without ever clicking it, must still be able to leave
       * with the value saved, which is exactly why closing is a separate,
       * always-available action rather than gated on `copied`.
       */}
      <Dialog open={Boolean(issued)} onOpenChange={() => {}}>
        <DialogContent
          showCloseButton={false}
          onEscapeKeyDown={(event) => event.preventDefault()}
          onPointerDownOutside={(event) => event.preventDefault()}
        >
          <DialogHeader>
            <DialogTitle>Token creato</DialogTitle>
            <DialogDescription>
              Copialo adesso: questa è l&apos;unica volta in cui sarà visibile. Il server ne
              conserva solo un hash e non potrà più mostrartelo — se lo perdi dovrai revocare
              questo token e crearne uno nuovo.
            </DialogDescription>
          </DialogHeader>
          <div className="flex gap-2">
            <Input readOnly value={issued?.token ?? ''} className="font-mono text-xs" />
            <Button variant="outline" size="icon" aria-label="Copia il token" onClick={copyIssued}>
              <Copy className="size-4" />
            </Button>
          </div>
          <DialogFooter>
            <Button onClick={() => setIssued(null)}>
              {copied ? 'Ho copiato il token, chiudi' : 'Ho salvato il token altrove, chiudi'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
