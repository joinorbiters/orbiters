import { useLocation, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { ApiError, requestPeople, type CompanyRequest } from '@/lib/api'
import { resolveAttribution } from '@/lib/utm'
import { LongTextField, TextField } from '@/wizard/fields'
import { Wizard, type Step } from '@/wizard/Wizard'

const EMPTY: CompanyRequest = {
  nome_azienda: '',
  referente: '',
  email: '',
  progetto: '',
  periodo_da: '',
  durata: '',
  budget_giornaliero: '',
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export const COMPANY_STEPS: Step<CompanyRequest>[] = [
  {
    id: 'nome_azienda',
    title: 'Come si chiama la tua azienda?',
    render: ({ value, set, autoFocus }) => (
      <TextField
        aria-label="Azienda"
        placeholder="ACME Srl"
        value={value.nome_azienda}
        onChange={(nome_azienda) => set({ nome_azienda })}
        autoFocus={autoFocus}
      />
    ),
    validate: (value) => (value.nome_azienda.trim() ? null : 'Serve il nome dell’azienda.'),
    summary: (value) => value.nome_azienda.trim(),
  },
  {
    id: 'referente',
    title: 'Chi sei, e dove ti scriviamo?',
    render: ({ value, set, autoFocus }) => (
      <div className="grid gap-3">
        <TextField
          aria-label="Referente"
          placeholder="Nome e cognome"
          value={value.referente}
          onChange={(referente) => set({ referente })}
          autoFocus={autoFocus}
        />
        <TextField
          aria-label="Email"
          type="email"
          inputMode="email"
          placeholder="nome@azienda.it"
          value={value.email}
          onChange={(email) => set({ email })}
        />
      </div>
    ),
    validate: (value) =>
      value.referente.trim() && EMAIL.test(value.email.trim())
        ? null
        : 'Servono un referente e un indirizzo email valido.',
    summary: (value) => `${value.referente.trim()} · ${value.email.trim()}`,
  },
  {
    id: 'progetto',
    title: 'Raccontaci il progetto in due righe',
    hint: 'Cosa serve fare, con che stack o competenze, e cosa deve uscirne. Shift+Invio per andare a capo.',
    render: ({ value, set, autoFocus }) => (
      <LongTextField
        aria-label="Progetto"
        placeholder="Dobbiamo rifare il backend del portale clienti…"
        value={value.progetto}
        onChange={(progetto) => set({ progetto })}
        autoFocus={autoFocus}
      />
    ),
    validate: (value) =>
      value.progetto.trim().length >= 20 ? null : 'Due righe bastano, ma servono: almeno venti caratteri.',
    summary: (value) => value.progetto.trim(),
  },
  {
    id: 'periodo_da',
    title: 'Da quando, e per quanto?',
    hint: 'Anche approssimativo: «da ottobre, per tre mesi».',
    render: ({ value, set, autoFocus }) => (
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField
          aria-label="Da quando"
          type="date"
          value={value.periodo_da}
          onChange={(periodo_da) => set({ periodo_da })}
          autoFocus={autoFocus}
        />
        <TextField
          aria-label="Per quanto"
          placeholder="3 mesi"
          value={value.durata}
          onChange={(durata) => set({ durata })}
        />
      </div>
    ),
    validate: (value) =>
      /^\d{4}-\d{2}-\d{2}$/.test(value.periodo_da) && value.durata.trim()
        ? null
        : 'Servono una data di inizio e una durata.',
    summary: (value) => (value.periodo_da ? `dal ${value.periodo_da}, ${value.durata.trim()}` : ''),
  },
  {
    id: 'budget_giornaliero',
    title: 'Che budget hai per una giornata?',
    hint: 'In euro, IVA esclusa. Serve a proporti le persone giuste, non a trattare.',
    render: ({ value, set, autoFocus }) => (
      <div className="flex items-center gap-3">
        <TextField
          aria-label="Budget a giornata"
          inputMode="decimal"
          placeholder="500"
          value={value.budget_giornaliero}
          onChange={(budget_giornaliero) => set({ budget_giornaliero })}
          autoFocus={autoFocus}
        />
        <span className="text-lg text-muted-foreground">€ / giorno</span>
      </div>
    ),
    validate: (value) => {
      const number = Number(value.budget_giornaliero.replace(',', '.'))
      return Number.isFinite(number) && number >= 1 && number <= 99999 ? null : 'Serve una cifra, in euro.'
    },
    summary: (value) => (value.budget_giornaliero ? `${value.budget_giornaliero} € / giorno` : ''),
  },
]

export function CompanyWizard() {
  const navigate = useNavigate()
  // The URL's own query string, from the router rather than `window`: the attribution
  // is whatever this page was opened with.
  const searchStr = useLocation({ select: (location) => location.searchStr })
  const [value, setValue] = useState<CompanyRequest>(EMPTY)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<{ message: string; step?: string } | null>(null)

  async function submit() {
    setSubmitting(true)
    setSubmitError(null)
    try {
      await requestPeople(
        { ...value, budget_giornaliero: value.budget_giornaliero.replace(',', '.') },
        resolveAttribution(searchStr),
      )
      void navigate({ to: '/grazie', search: { chi: 'azienda' } })
    } catch (error) {
      const failure = error instanceof ApiError ? error : null
      // `durata` shares the step with `periodo_da`; anything else names its own step.
      const field = failure?.fields[0]
      setSubmitError({
        message: failure?.message ?? 'Non siamo riusciti a inviare la richiesta. Riprova.',
        step: field === 'durata' ? 'periodo_da' : field,
      })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Wizard
      title="Cerchi persone"
      steps={COMPANY_STEPS}
      value={value}
      set={(patch) => setValue((current) => ({ ...current, ...patch }))}
      onSubmit={() => void submit()}
      submitting={submitting}
      submitError={submitError}
      submitLabel="Invia la richiesta"
    />
  )
}
