import { useLocation, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { ApiError, applyAsFreelancer, type FreelancerApplication } from '@/lib/api'
import { readUtm } from '@/lib/utm'
import { ChoiceField, FileField, LinksField, TextField } from '@/wizard/fields'
import { Wizard, type Step } from '@/wizard/Wizard'

const EMPTY: FreelancerApplication = {
  nome: '',
  cognome: '',
  email: '',
  linkedin_url: '',
  tariffa_giornaliera: '',
  posizione: '',
  remoto: '',
  links: [],
  cv: null,
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const LINKEDIN = /^https:\/\/([a-z0-9-]+\.)*linkedin\.com\//i
const MAX_CV = 5 * 1024 * 1024

export const FREELANCER_STEPS: Step<FreelancerApplication>[] = [
  {
    id: 'nome',
    title: 'Come ti chiami?',
    render: ({ value, set, autoFocus }) => (
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField
          aria-label="Nome"
          placeholder="Nome"
          value={value.nome}
          onChange={(nome) => set({ nome })}
          autoFocus={autoFocus}
        />
        <TextField
          aria-label="Cognome"
          placeholder="Cognome"
          value={value.cognome}
          onChange={(cognome) => set({ cognome })}
        />
      </div>
    ),
    validate: (value) =>
      value.nome.trim() && value.cognome.trim() ? null : 'Servono nome e cognome.',
    summary: (value) => `${value.nome.trim()} ${value.cognome.trim()}`.trim(),
  },
  {
    id: 'email',
    title: 'A che indirizzo ti scriviamo?',
    render: ({ value, set, autoFocus }) => (
      <TextField
        aria-label="Email"
        type="email"
        inputMode="email"
        placeholder="nome@studio.it"
        value={value.email}
        onChange={(email) => set({ email })}
        autoFocus={autoFocus}
      />
    ),
    validate: (value) => (EMAIL.test(value.email.trim()) ? null : 'Serve un indirizzo email valido.'),
    summary: (value) => value.email.trim(),
  },
  {
    id: 'linkedin_url',
    title: 'Il tuo profilo LinkedIn',
    hint: 'Se ce l’hai. Incolla l’indirizzo completo.',
    optional: true,
    render: ({ value, set, autoFocus }) => (
      <TextField
        aria-label="Profilo LinkedIn"
        inputMode="url"
        placeholder="https://www.linkedin.com/in/…"
        value={value.linkedin_url}
        onChange={(linkedin_url) => set({ linkedin_url })}
        autoFocus={autoFocus}
      />
    ),
    validate: (value) =>
      !value.linkedin_url.trim() || LINKEDIN.test(value.linkedin_url.trim())
        ? null
        : 'Serve l’indirizzo https di un profilo su linkedin.com, oppure niente.',
    summary: (value) => value.linkedin_url.trim(),
  },
  {
    id: 'cv',
    title: 'Il tuo CV',
    hint: 'Un PDF, al massimo 5 MB. Lo leggiamo noi e chi ti proporrà un progetto; puoi chiederci di cancellarlo quando vuoi.',
    render: ({ value, set }) => (
      <FileField
        value={value.cv}
        onChange={(cv) => set({ cv })}
        accept="application/pdf,.pdf"
        hint="PDF fino a 5 MB"
      />
    ),
    validate: (value) => {
      if (!value.cv) return 'Serve il CV, in PDF.'
      if (value.cv.size > MAX_CV) return 'Il CV può pesare al massimo 5 MB.'
      if (value.cv.type && value.cv.type !== 'application/pdf') return 'Il CV deve essere un PDF.'
      return null
    },
    summary: (value) => value.cv?.name ?? '',
  },
  {
    id: 'tariffa_giornaliera',
    title: 'Quanto costa una tua giornata?',
    hint: 'In euro, IVA esclusa. Una cifra indicativa: serve a proporti i progetti giusti.',
    render: ({ value, set, autoFocus }) => (
      <div className="flex items-center gap-3">
        <TextField
          aria-label="Tariffa a giornata"
          inputMode="decimal"
          placeholder="450"
          value={value.tariffa_giornaliera}
          onChange={(tariffa_giornaliera) => set({ tariffa_giornaliera })}
          autoFocus={autoFocus}
        />
        <span className="text-lg text-muted-foreground">€ / giorno</span>
      </div>
    ),
    validate: (value) => {
      const number = Number(value.tariffa_giornaliera.replace(',', '.'))
      return Number.isFinite(number) && number >= 1 && number <= 99999
        ? null
        : 'Serve una cifra, in euro.'
    },
    summary: (value) => (value.tariffa_giornaliera ? `${value.tariffa_giornaliera} € / giorno` : ''),
  },
  {
    id: 'posizione',
    title: 'Cosa fai?',
    hint: 'Il ruolo con cui ti presenti: «Backend developer», «AI engineer», «Fractional CTO».',
    render: ({ value, set, autoFocus }) => (
      <TextField
        aria-label="Posizione"
        placeholder="Backend developer"
        value={value.posizione}
        onChange={(posizione) => set({ posizione })}
        autoFocus={autoFocus}
      />
    ),
    validate: (value) => (value.posizione.trim() ? null : 'Serve una posizione.'),
    summary: (value) => value.posizione.trim(),
  },
  {
    id: 'remoto',
    title: 'Come preferisci lavorare?',
    render: ({ value, set }) => (
      <ChoiceField
        value={value.remoto}
        onChange={(remoto) => set({ remoto })}
        options={[
          { value: 'remoto', label: 'Da remoto', hint: 'Ovunque, con le call che servono.' },
          { value: 'ibrido', label: 'Ibrido', hint: 'Qualche giorno in sede va bene.' },
          { value: 'in_sede', label: 'In sede', hint: 'Preferisco essere dal cliente.' },
        ]}
      />
    ),
    validate: (value) => (value.remoto ? null : 'Scegli una delle tre.'),
    summary: (value) =>
      ({ remoto: 'Da remoto', ibrido: 'Ibrido', in_sede: 'In sede', '': '' })[value.remoto],
  },
  {
    id: 'links',
    title: 'Altri link che vuoi farci vedere',
    hint: 'GitHub, portfolio, sito: uno per riga, con https.',
    optional: true,
    render: ({ value, set, autoFocus }) => (
      <LinksField value={value.links} onChange={(links) => set({ links })} autoFocus={autoFocus} />
    ),
    validate: (value) => {
      const links = value.links.map((link) => link.trim()).filter(Boolean)
      if (links.length > 10) return 'Al massimo dieci link.'
      return links.every((link) => /^https:\/\/[^\s]+\.[^\s]+/.test(link))
        ? null
        : 'Ogni link deve essere un indirizzo https completo.'
    },
    summary: (value) => value.links.map((link) => link.trim()).filter(Boolean).join(', '),
  },
]

export function FreelancerWizard() {
  const navigate = useNavigate()
  // The URL's own query string, from the router rather than `window`: the attribution
  // is whatever this page was opened with.
  const searchStr = useLocation({ select: (location) => location.searchStr })
  const [value, setValue] = useState<FreelancerApplication>(EMPTY)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<{ message: string; step?: string } | null>(null)

  async function submit() {
    setSubmitting(true)
    setSubmitError(null)
    try {
      await applyAsFreelancer(value, readUtm(searchStr))
      void navigate({ to: '/grazie', search: { chi: 'freelance' } })
    } catch (error) {
      const failure = error instanceof ApiError ? error : null
      setSubmitError({
        message: failure?.message ?? 'Non siamo riusciti a inviare la candidatura. Riprova.',
        step: failure?.fields[0],
      })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Wizard
      title="Entra in Orbiters"
      steps={FREELANCER_STEPS}
      value={value}
      set={(patch) => setValue((current) => ({ ...current, ...patch }))}
      onSubmit={() => void submit()}
      submitting={submitting}
      submitError={submitError}
      submitLabel="Invia la candidatura"
    />
  )
}
