/**
 * What a new space still has to do, read from the data and never stored (spec
 * 2026-09-12 §6.7): a step is done because the thing exists. Six cheap reads, one row
 * each, so the Home of an empty space can say what comes first without a table of its
 * own. The root and any space that has been used see nothing: every step is done.
 */
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

export type StepId = 'fiscali' | 'cliente' | 'lavoro' | 'documento'

export interface FirstStep {
  id: StepId
  title: string
  hint: string
  to: string
  done: boolean
}

export interface FirstStepsState {
  loading: boolean
  steps: FirstStep[]
  doneCount: number
  allDone: boolean
  /** Whether the space has at least one personal access token: the assistant is connected. */
  assistantConnected: boolean
}

/** The one preference this panel keeps, and it keeps it in the browser: whose it is. */
export const HIDE_KEY = 'pigrocrm.primi-passi.nascosto'

export function isHidden(): boolean {
  try {
    return window.localStorage.getItem(HIDE_KEY) === '1'
  } catch {
    return false
  }
}

export function hide(): void {
  try {
    window.localStorage.setItem(HIDE_KEY, '1')
  } catch {
    // A browser that refuses storage shows the panel again next time. Fine.
  }
}

/** Where the «Collega l'assistente» button goes. ORB-170 is shipping the «Collega un
 *  agente» dialog in the sidebar; until the Home can open that dialog, the token page
 *  is the place where the assistant is connected today. */
export const CONNECT_ASSISTANT_TO = '/app/token'

async function hasAny(path: '/api/customers' | '/api/deals' | '/api/time-entries' | '/api/documents'): Promise<boolean> {
  const { data } = await api.GET(path, { params: { query: { limit: 1 } } } as never)
  const page = data as { items?: unknown[] } | undefined
  return (page?.items?.length ?? 0) > 0
}

async function fiscalDataSaved(): Promise<boolean> {
  // 404 until the emitter profile is saved once: not an error here, a step to do.
  const { data, response } = await api.GET('/api/emitter')
  if (response.status === 404 || !data) return false
  const profile = data as { partita_iva?: string | null; codice_fiscale?: string | null }
  return Boolean(profile.partita_iva || profile.codice_fiscale)
}

async function hasToken(): Promise<boolean> {
  const { data } = await api.GET('/api/tokens')
  return Array.isArray(data) && data.length > 0
}

const OPTIONS = { retry: false, staleTime: 30_000 } as const

export function useFirstSteps(): FirstStepsState {
  const fiscali = useQuery({ queryKey: ['first-steps', 'fiscali'], queryFn: fiscalDataSaved, ...OPTIONS })
  const cliente = useQuery({ queryKey: ['first-steps', 'cliente'], queryFn: () => hasAny('/api/customers'), ...OPTIONS })
  const deal = useQuery({ queryKey: ['first-steps', 'deal'], queryFn: () => hasAny('/api/deals'), ...OPTIONS })
  const ore = useQuery({ queryKey: ['first-steps', 'ore'], queryFn: () => hasAny('/api/time-entries'), ...OPTIONS })
  const documento = useQuery({ queryKey: ['first-steps', 'documento'], queryFn: () => hasAny('/api/documents'), ...OPTIONS })
  const token = useQuery({ queryKey: ['first-steps', 'token'], queryFn: hasToken, ...OPTIONS })

  const all = [fiscali, cliente, deal, ore, documento, token]
  const loading = all.some((q) => q.isPending)
  // A read that failed counts as done: a panel that nags because a request broke would
  // be the untrue thing on the page. The charts beside it already say when the API is down.
  const value = (q: { data?: boolean; isError: boolean }) => (q.isError ? true : (q.data ?? false))

  const steps: FirstStep[] = [
    {
      id: 'fiscali',
      title: 'I tuoi dati fiscali',
      hint: 'Partita IVA o codice fiscale, indirizzo, regime: finiscono su offerte e fatture.',
      to: '/app/impostazioni/emittente',
      done: value(fiscali),
    },
    {
      id: 'cliente',
      title: 'Il primo cliente',
      hint: 'Un’azienda o una persona per cui lavori. Tutto il resto parte da qui.',
      to: '/app/clienti',
      done: value(cliente),
    },
    {
      id: 'lavoro',
      title: 'Il primo deal, o le prime ore',
      hint: 'Una trattativa in corso, oppure le ore che hai già lavorato.',
      to: '/app/deal',
      done: value(deal) || value(ore),
    },
    {
      id: 'documento',
      title: 'La prima offerta',
      hint: 'Dal deal, «Crea documento»: il template «Offerta» è già pronto.',
      to: '/app/deal',
      done: value(documento),
    },
  ]
  const doneCount = steps.filter((s) => s.done).length
  return {
    loading,
    steps,
    doneCount,
    allDone: doneCount === steps.length,
    assistantConnected: value(token),
  }
}
