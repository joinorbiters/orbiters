import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { fieldErrorFrom, toProblem, type ProblemDetail } from '@/lib/api'
import {
  useFiscalProfile,
  useSaveFiscalProfile,
  type FiscalProfile,
} from '@/features/invoices/queries'

interface FiscalField {
  name:
    | 'codice_regime'
    | 'aliquota_iva_default'
    | 'natura_default'
    | 'riferimento_normativo'
    | 'soglia_bollo'
    | 'importo_bollo'
    | 'condizioni_pagamento'
    | 'modalita_pagamento'
    | 'giorni_scadenza'
    | 'iban'
  label: string
  hint?: string
}

/**
 * `applica_bollo` is a boolean and lives outside this list; everything else is a text
 * input because the values are codes and decimals the backend validates, and a
 * client-side guess at their shape would only produce a second, weaker validator.
 */
const FIELDS: readonly FiscalField[] = [
  { name: 'codice_regime', label: 'Regime fiscale', hint: 'RF19 = forfettario' },
  { name: 'aliquota_iva_default', label: 'Aliquota IVA predefinita' },
  { name: 'natura_default', label: 'Natura', hint: 'Obbligatoria quando l’aliquota è 0' },
  { name: 'riferimento_normativo', label: 'Riferimento normativo' },
  { name: 'soglia_bollo', label: 'Soglia bollo' },
  { name: 'importo_bollo', label: 'Importo bollo' },
  { name: 'condizioni_pagamento', label: 'Condizioni di pagamento', hint: 'TP02' },
  { name: 'modalita_pagamento', label: 'Modalità di pagamento', hint: 'MP05' },
  { name: 'giorni_scadenza', label: 'Giorni di scadenza' },
  { name: 'iban', label: 'IBAN' },
]

type Values = Record<FiscalField['name'], string> & { applica_bollo: boolean }

function emptyValues(): Values {
  return {
    codice_regime: 'RF19',
    aliquota_iva_default: '0.00',
    natura_default: 'N2.2',
    riferimento_normativo: '',
    soglia_bollo: '77.47',
    importo_bollo: '2.00',
    condizioni_pagamento: 'TP02',
    modalita_pagamento: 'MP05',
    giorni_scadenza: '30',
    iban: '',
    applica_bollo: true,
  }
}

function valuesFrom(profile: FiscalProfile): Values {
  const values = emptyValues()
  for (const field of FIELDS) {
    const stored = profile[field.name]
    values[field.name] = stored === null || stored === undefined ? '' : String(stored)
  }
  values.applica_bollo = profile.applica_bollo
  return values
}

export function FiscalPanel() {
  const profile = useFiscalProfile()

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-medium">Fiscale</h2>
        <p className="text-muted-foreground text-sm">
          I parametri che decidono aliquota, natura e bollo su ogni riga di fattura. Una
          fattura emessa conserva una copia di questi valori, quindi cambiarli qui non
          tocca i documenti già emessi.
        </p>
      </div>

      {profile.isError ? <QueryErrorBanner error={profile.error} /> : null}

      {!profile.isLoading && !profile.isError && profile.data === null ? (
        <p className="text-muted-foreground text-sm">
          Profilo non ancora configurato: senza di esso non è possibile emettere fatture.
        </p>
      ) : null}

      {profile.isLoading || profile.isError ? null : (
        // A failed read hides the form entirely -- `isError`, not just `isLoading`.
        // A 404 is not an error here (`useFiscalProfile` maps it to `null`, "not configured
        // yet"), so this branch only fires on a *real* failure: the row may well exist
        // and simply be unreadable. Rendering the blank form in that state invites
        // somebody to fill it in and press Salva, and the save is a PUT of every key --
        // it would overwrite a stored profile the panel was never able to show them.
        // Keyed on identity so the form seeds at mount rather than in an effect: one
        // render with the right values, and a later refetch cannot overwrite what the
        // user is typing.
        <FiscalForm key={profile.data?.id ?? 'nuovo'} profile={profile.data ?? null} />
      )}
    </div>
  )
}

function FiscalForm({ profile }: { profile: FiscalProfile | null }) {
  const save = useSaveFiscalProfile()
  const [values, setValues] = useState<Values>(() =>
    profile ? valuesFrom(profile) : emptyValues(),
  )
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  function submit() {
    setProblem(null)
    save.mutate(values, {
      onSuccess: () => toast.success('Profilo fiscale salvato'),
      onError: (error) => setProblem(toProblem(error)),
    })
  }

  const fieldError = problem ? fieldErrorFrom(problem) : null

  return (
    <div className="space-y-4">
      {problem && !fieldError ? <QueryErrorBanner error={problem} /> : null}

      <div className="grid gap-4 sm:grid-cols-2">
        {FIELDS.map((field) => (
          <div key={field.name} className="space-y-2">
            <Label htmlFor={`fiscal-${field.name}`}>{field.label}</Label>
            <Input
              id={`fiscal-${field.name}`}
              value={values[field.name]}
              aria-invalid={fieldError?.field === field.name ? true : undefined}
              onChange={(event) =>
                setValues((previous) => ({ ...previous, [field.name]: event.target.value }))
              }
            />
            {fieldError?.field === field.name ? (
              <p className="text-destructive text-sm">{fieldError.message}</p>
            ) : field.hint ? (
              <p className="text-muted-foreground text-xs">{field.hint}</p>
            ) : null}
          </div>
        ))}
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={values.applica_bollo}
          onChange={(event) =>
            setValues((previous) => ({ ...previous, applica_bollo: event.target.checked }))
          }
        />
        Applica il bollo virtuale sopra la soglia
      </label>

      <div className="flex justify-end">
        <Button onClick={submit} disabled={save.isPending}>
          Salva
        </Button>
      </div>
    </div>
  )
}
