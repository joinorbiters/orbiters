import { Link } from '@tanstack/react-router'
import { ArrowUpRight, Download, LogOut, Pencil } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { member } from '@/lib/api'
import { formatBytes } from '@/lib/format'
import { toApplication, useMember, useMemberLogout } from '@/lib/member'
import { FREELANCER_STEPS } from '@/pages/FreelancerWizard'

const PIGROCRM_URL = 'https://pigro.joinorbiters.com/app/registrati'

/** What the person sent, under the wizard's own questions, and the perks. The email is
 *  shown and not editable: it is the address the link proved. */
export function Area() {
  const me = useMember()
  const logout = useMemberLogout()
  if (!me.data) return null
  const profile = me.data
  const value = toApplication(profile)
  const steps = FREELANCER_STEPS.filter((step) => step.id !== 'email' && step.id !== 'cv')

  return (
    <div className="mx-auto max-w-2xl space-y-10">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">La tua area</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">
            {profile.nome} {profile.cognome}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Ti scriviamo a <span className="font-medium text-foreground">{profile.email}</span>.
            Per cambiare indirizzo, rifai la candidatura con quello nuovo.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button asChild variant="outline" size="sm">
            {/* '/io/modifica' is Task 8's route: the router doesn't type it yet, so the
                literal needs a cast until that task adds it to the tree. */}
            <Link to={'/io/modifica' as never}>
              <Pencil className="mr-2 size-4" />
              Modifica
            </Link>
          </Button>
          <Button variant="ghost" size="sm" onClick={() => logout.mutate()} disabled={logout.isPending}>
            <LogOut className="mr-2 size-4" />
            Esci
          </Button>
        </div>
      </header>

      <section aria-label="Quello che ci hai mandato">
        <dl className="divide-y rounded-2xl border bg-card">
          {steps.map((step) => (
            <div key={step.id} className="flex items-start gap-4 px-4 py-3 text-sm">
              <dt className="w-40 shrink-0 text-muted-foreground">{step.title}</dt>
              <dd className="min-w-0 flex-1 break-words font-medium">{step.summary(value) || '—'}</dd>
            </div>
          ))}
          <div className="flex items-start gap-4 px-4 py-3 text-sm">
            <dt className="w-40 shrink-0 text-muted-foreground">Il tuo CV</dt>
            <dd className="min-w-0 flex-1">
              <a href={member.cvUrl} className="inline-flex items-center gap-1.5 font-medium underline-offset-2 hover:underline">
                <Download className="size-4" aria-hidden="true" />
                {profile.cv_filename}
                <span className="font-normal text-muted-foreground">({formatBytes(profile.cv_size)})</span>
              </a>
            </dd>
          </div>
        </dl>
      </section>

      <section aria-label="I tuoi vantaggi" className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-3 rounded-2xl border-2 border-foreground bg-card p-6">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Per chi è dentro</p>
          <h2 className="text-lg font-semibold">PigroCRM è tuo, gratis</h2>
          <p className="text-sm text-muted-foreground">
            Preventivo, contratto, fattura, ore: fatturare e farti pagare, con i dati fiscali già giusti.
          </p>
          <Button asChild className="mt-auto self-start">
            <a href={PIGROCRM_URL}>
              Apri PigroCRM
              <ArrowUpRight className="ml-2 size-4" />
            </a>
          </Button>
        </div>
        <div className="flex flex-col gap-3 rounded-2xl border border-dashed bg-muted/40 p-6 text-muted-foreground">
          <p className="text-xs font-medium tracking-wide uppercase">Prossimamente</p>
          <h2 className="text-lg font-semibold">Altro in arrivo</h2>
          <p className="text-sm">Stiamo mettendo insieme altre cose per chi è dentro. Ti scriviamo noi.</p>
        </div>
      </section>
    </div>
  )
}
