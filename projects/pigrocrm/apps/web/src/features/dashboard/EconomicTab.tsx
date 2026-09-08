import { Link } from '@tanstack/react-router'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Skeleton } from '@/components/ui/skeleton'
import { BigNumber } from './charts'
import { money, percent } from './format'
import { Freshness } from './Freshness'
import { MonthlyBars } from './MonthlyBars'
import type { Periodo } from './periodo'
import { useEconomicOverview, type FiscalEstimate } from './queries'

/** The year the picker's start date names: cash and taxes are told by the year. A date,
 *  not an amount, so reading it through `Date` is not the coercion criterion 14 bans. */
function yearOf(periodo: Periodo): number {
  return new Date(`${periodo.da}T00:00:00`).getFullYear()
}

function dovuto(estimate: FiscalEstimate | null): string {
  return estimate?.totale_dovuto ? money(estimate.totale_dovuto) : '—'
}

export function EconomicTab({ periodo }: { periodo: Periodo }) {
  const anno = yearOf(periodo)
  const query = useEconomicOverview(anno)

  if (query.isError) return <QueryErrorBanner error={query.error} />
  if (query.isPending || !query.data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  const { cassa, fiscale, fiscale_proiettato, netto_effettivo, netto_proiettato } = query.data

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          Vista economica {anno}: ricavi incassati, costi passivi e stima fiscale.
        </p>
        <Freshness
          calcolatoAlle={query.data.calcolato_alle}
          onRefresh={() => void query.refetch()}
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <BigNumber label="Ricavi incassati" value={money(cassa.incassato)} tone="accent" />
        <BigNumber
          label="Ricavi proiettati"
          value={money(cassa.proiettato)}
          hint={`Incassato ${money(cassa.incassato)} · da incassare ${money(cassa.da_incassare)} · bozze e proforma ${money(cassa.bozze)}`}
        />
        <BigNumber label="Costi passivi" value={money(cassa.costi)} />
        <BigNumber
          label="Totale lordo effettivo"
          value={money(cassa.lordo_effettivo)}
          hint="incassato meno costi"
        />
        {fiscale ? (
          <>
            <BigNumber
              label="Imponibile forfettario stimato"
              value={money(fiscale.imponibile ?? '0.00')}
              hint={
                fiscale_proiettato?.imponibile
                  ? `con proiezione ${money(fiscale_proiettato.imponibile)}`
                  : undefined
              }
            />
            <BigNumber
              label="Totale da saldare"
              value={dovuto(fiscale)}
              hint={`imposta sostitutiva ${money(fiscale.imposta_sostitutiva ?? '0.00')} · INPS ${money(fiscale.contributi ?? '0.00')}`}
            />
            <BigNumber
              label="Totale da saldare con proiezione"
              value={dovuto(fiscale_proiettato)}
              hint={`su ricavi proiettati ${money(cassa.proiettato)}`}
            />
            <BigNumber
              label="Totale netto ricavi"
              value={netto_effettivo ? money(netto_effettivo) : '—'}
              hint="lordo effettivo meno tasse stimate"
            />
            <BigNumber
              label="Totale netto ricavi con proiezione"
              value={netto_proiettato ? money(netto_proiettato) : '—'}
              hint={`lordo proiettato ${money(cassa.lordo_proiettato)} meno tasse stimate`}
            />
          </>
        ) : (
          <div className="border bg-card p-4 sm:col-span-2">
            <p className="text-sm text-muted-foreground">Stima fiscale</p>
            <p className="mt-1 text-sm">
              Non disponibile qui: serve un profilo fiscale configurato e un account
              amministratore.{' '}
              <Link to="/app/analisi/fiscale" className="underline underline-offset-2">
                Apri la stima fiscale
              </Link>
            </p>
          </div>
        )}
      </div>

      <MonthlyBars
        title={`Andamento economico ${anno}`}
        months={cassa.mesi}
        series={['incassato', 'costi']}
        shares="quote_andamento"
      />
      <MonthlyBars
        title={`Proiezione economica ${anno}`}
        months={cassa.mesi}
        series={['incassato', 'da_incassare', 'bozze', 'costi']}
        shares="quote_proiezione"
      />

      {fiscale && (
        <p className="border bg-muted/40 px-4 py-3 text-sm text-muted-foreground">
          Stima basata sul regime forfettario: coefficiente di redditività{' '}
          {percent(fiscale.coefficiente_redditivita)}, imposta sostitutiva{' '}
          {percent(fiscale.aliquota_imposta_sostitutiva)}, INPS {percent(fiscale.aliquota_inps)} su
          reddito netto. È una stima, non una dichiarazione.{' '}
          <Link to="/app/analisi/fiscale" className="underline underline-offset-2">
            Apri la stima fiscale
          </Link>
        </p>
      )}
    </div>
  )
}
