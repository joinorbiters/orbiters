import { useState } from 'react'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { toIsoMonth } from '@/lib/dates'
import { useUsers } from './queries'
import { useClosePeriod, usePeriodLocks, useReopenPeriod } from './queries.timetracking'

const MESI = [
  'gennaio',
  'febbraio',
  'marzo',
  'aprile',
  'maggio',
  'giugno',
  'luglio',
  'agosto',
  'settembre',
  'ottobre',
  'novembre',
  'dicembre',
]

/** `marzo 2026`. The same long-form Italian label `period_label` produces on the
 *  backend, so a `Conflict` naming a month and this list read identically. */
function label(anno: number, mese: number): string {
  return `${MESI[mese - 1] ?? mese} ${anno}`
}

const stamp = new Intl.DateTimeFormat('it-IT', { dateStyle: 'medium', timeStyle: 'short' })

export function PeriodsPanel() {
  const locks = usePeriodLocks()
  const users = useUsers()
  const close = useClosePeriod()
  const reopen = useReopenPeriod()
  const [problem, setProblem] = useState<ProblemDetail | null>(null)
  const [pending, setPending] = useState<{ anno: number; mese: number } | null>(null)
  // `toIsoMonth`, never `toISOString().slice(0, 7)`: on the last evening of a month east
  // of Greenwich the UTC route opens the picker on the month that has not started yet.
  const [mese, setMese] = useState(() => toIsoMonth(new Date()))

  // The failed request replaces the list rather than colouring a row inside it: an
  // empty `<ul>` next to a banner would still be readable as "nothing is closed", which
  // is a claim this panel cannot make when it never got an answer.
  if (locks.isError) return <QueryErrorBanner error={locks.error} />

  // Resolved from the users list rather than from a name embedded in the lock: the lock
  // stores an id, and a renamed user must show its current name here.
  const names = new Map((users.data ?? []).map((user) => [user.id, user.nome]))

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-semibold">Periodi chiusi</h2>
        <p className="text-sm text-muted-foreground">
          Chiudere un periodo non è obbligatorio. Serve quando i numeri di un mese sono già
          stati riportati: da quel momento nessuna voce di ore e nessun costo datati in quel
          mese possono essere creati, modificati o cancellati. Le fatture hanno regole proprie
          e non vengono toccate.
        </p>
      </div>

      {problem && (
        <p
          role="alert"
          className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {problem.detail}
        </p>
      )}

      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-2">
          <Label htmlFor="periodo-da-chiudere">Chiudi il mese</Label>
          <Input
            id="periodo-da-chiudere"
            type="month"
            value={mese}
            onChange={(event) => setMese(event.target.value)}
            className="w-40"
          />
        </div>
        <Button
          disabled={close.isPending}
          onClick={() => {
            const [anno, numero] = mese.split('-').map(Number)
            setProblem(null)
            // No client-side bounds check: `PeriodLockCreate` carries them, and a second
            // opinion here is how this screen and the API start disagreeing about what a
            // valid month is. A nonsense value comes back as a problem document and is
            // shown above, in the server's own words.
            close.mutate(
              { anno: anno ?? 0, mese: numero ?? 0 },
              { onError: (error) => setProblem(toProblem(error)) },
            )
          }}
        >
          Chiudi periodo
        </Button>
      </div>

      <ul className="divide-y rounded-lg border">
        {(locks.data ?? []).map((lock) => (
          <li key={`${lock.anno}-${lock.mese}`} className="flex items-center justify-between p-3">
            <div>
              <p className="font-medium">{label(lock.anno, lock.mese)}</p>
              <p className="text-xs text-muted-foreground">
                Chiuso il {stamp.format(new Date(lock.chiuso_il))}
                {lock.chiuso_da ? ` da ${names.get(lock.chiuso_da) ?? lock.chiuso_da}` : ''}
              </p>
            </div>
            {pending?.anno === lock.anno && pending?.mese === lock.mese ? (
              <div className="flex gap-2">
                <Button variant="ghost" onClick={() => setPending(null)}>
                  Annulla
                </Button>
                <Button
                  variant="destructive"
                  disabled={reopen.isPending}
                  onClick={() => {
                    setProblem(null)
                    reopen.mutate(
                      { anno: lock.anno, mese: lock.mese },
                      {
                        onSuccess: () => setPending(null),
                        onError: (error) => setProblem(toProblem(error)),
                      },
                    )
                  }}
                >
                  Conferma
                </Button>
              </div>
            ) : (
              // Confirmed, and it leaves a trace: a period is not reopened by accident
              // and is not reopened in silence -- the service writes an activity.
              <Button
                variant="outline"
                onClick={() => setPending({ anno: lock.anno, mese: lock.mese })}
              >
                Riapri
              </Button>
            )}
          </li>
        ))}
        {locks.data?.length === 0 && !locks.isLoading && (
          <li className="p-3 text-sm text-muted-foreground">Nessun periodo chiuso.</li>
        )}
      </ul>
    </div>
  )
}
