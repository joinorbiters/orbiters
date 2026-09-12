/**
 * What a new space still has to do, read from the data and never stored (spec
 * 2026-09-12 §6.7): a step is done because the thing exists. Six one-row reads, so the
 * Home of an empty space can say what comes first without a table of its own. The root
 * and any space that has been used see nothing: every step is done.
 *
 * The keys sit under the prefixes the rest of the app invalidates (`['customers', …]`,
 * `['emitter', …]`, `['tokens', userId, …]`), so creating the first customer, saving
 * the emitter or minting a token refreshes the panel on the next Home without waiting
 * out `staleTime`.
 */
import { useQuery } from '@tanstack/react-query'
import { api, toProblem } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { queryKeys } from '@/lib/query'
import { tenantPrefix } from '@/lib/tenant'

export type StepId = 'fiscali' | 'cliente' | 'lavoro' | 'documento'
export type StepTarget = '/app/impostazioni/emittente' | '/app/clienti' | '/app/deal'

export interface FirstStep {
  id: StepId
  title: string
  hint: string
  to: StepTarget
  /** Whether the person who is looking can do this step themselves. */
  canDo: boolean
  done: boolean
}

export interface FirstStepsState {
  loading: boolean
  steps: FirstStep[]
  doneCount: number
  allDone: boolean
  /** Whether this user has a personal access token: their assistant is connected. */
  assistantConnected: boolean
}

/** The one preference this panel keeps, in the browser, per space and per user: two
 *  spaces share the origin (`/<slug>/app`), and «Nascondi» in one must not hide the
 *  other's list. */
export function hideKey(userId: string): string {
  return `pigrocrm.primi-passi.nascosto:${tenantPrefix || '/'}:${userId}`
}

export function isHidden(userId: string): boolean {
  try {
    return window.localStorage.getItem(hideKey(userId)) === '1'
  } catch {
    return false
  }
}

export function hide(userId: string): void {
  try {
    window.localStorage.setItem(hideKey(userId), '1')
  } catch {
    // A browser that refuses storage shows the panel again next time. Fine.
  }
}

/** Where the «Collega l'assistente» button goes. ORB-170 is shipping the «Collega un
 *  agente» dialog in the sidebar; until the Home can open that dialog, the token page
 *  is the place where the assistant is connected today. */
export const CONNECT_ASSISTANT_TO = '/app/token' as const

const SCOPE = { scope: 'first-steps', limit: 1 } as const

/** Throws for any answer that is not 2xx, except the one the caller names as an
 *  ordinary state (the emitter's 404). A step that could not be read counts as done
 *  (`value` below): a panel that nags because a request broke would be the untrue thing
 *  on the page, and the charts beside it already say when the API is down. */
function settled<T>(
  result: { data?: T; error?: unknown; response: Response },
  okStatuses: readonly number[] = [],
): T | undefined {
  if (result.error !== undefined && !okStatuses.includes(result.response.status)) {
    throw toProblem(result.error, result.response.status)
  }
  return result.data
}

async function hasCustomers(): Promise<boolean> {
  const page = settled(await api.GET('/api/customers', { params: { query: { limit: 1 } } }))
  return (page?.items.length ?? 0) > 0
}

async function hasDeals(): Promise<boolean> {
  const page = settled(await api.GET('/api/deals', { params: { query: { limit: 1 } } }))
  return (page?.items.length ?? 0) > 0
}

async function hasTimeEntries(): Promise<boolean> {
  const page = settled(await api.GET('/api/time-entries', { params: { query: { limit: 1 } } }))
  return (page?.items.length ?? 0) > 0
}

async function hasDocuments(): Promise<boolean> {
  const page = settled(await api.GET('/api/documents', { params: { query: { limit: 1 } } }))
  return (page?.items.length ?? 0) > 0
}

async function fiscalDataSaved(): Promise<boolean> {
  // 404 until the emitter profile is saved once: not an error here, a step to do.
  const profile = settled(await api.GET('/api/emitter'), [404])
  return Boolean(profile?.partita_iva || profile?.codice_fiscale)
}

async function hasToken(): Promise<boolean> {
  const tokens = settled(await api.GET('/api/tokens'))
  return (tokens?.length ?? 0) > 0
}

const OPTIONS = { retry: false, staleTime: 30_000 } as const

export function useFirstSteps({ hidden }: { hidden: boolean }): FirstStepsState {
  const { user } = useAuth()
  const userId = user?.id ?? ''
  const isAdmin = user?.ruolo === 'admin'
  // Only the token is read while the list is hidden: the card stays until the assistant
  // is connected, the five other reads are not worth a request nobody will see.
  const steps = { ...OPTIONS, enabled: !hidden }
  const token = useQuery({
    queryKey: [...queryKeys.tokens(userId), 'first-steps'],
    queryFn: hasToken,
    ...OPTIONS,
  })
  const fiscali = useQuery({ queryKey: [...queryKeys.emitter, 'first-steps'], queryFn: fiscalDataSaved, ...steps })
  const cliente = useQuery({ queryKey: queryKeys.customers(SCOPE), queryFn: hasCustomers, ...steps })
  const deal = useQuery({ queryKey: queryKeys.deals(SCOPE), queryFn: hasDeals, ...steps })
  const ore = useQuery({ queryKey: queryKeys.timeEntries(SCOPE), queryFn: hasTimeEntries, ...steps })
  const documento = useQuery({ queryKey: queryKeys.documents(SCOPE), queryFn: hasDocuments, ...steps })

  const active = hidden ? [token] : [token, fiscali, cliente, deal, ore, documento]
  const loading = active.some((q) => q.isPending)
  const value = (q: { data?: boolean; isError: boolean }) => (q.isError ? true : (q.data ?? false))

  const list: FirstStep[] = [
    {
      id: 'fiscali',
      title: 'I tuoi dati fiscali',
      hint: isAdmin
        ? 'Partita IVA o codice fiscale, indirizzo, regime: finiscono su offerte e fatture.'
        : 'Li imposta l’amministratore dello spazio, in Impostazioni.',
      to: '/app/impostazioni/emittente',
      canDo: isAdmin,
      done: value(fiscali),
    },
    {
      id: 'cliente',
      title: 'Il primo cliente',
      hint: 'Un’azienda o una persona per cui lavori. Tutto il resto parte da qui.',
      to: '/app/clienti',
      canDo: true,
      done: value(cliente),
    },
    {
      id: 'lavoro',
      title: 'Il primo deal, o le prime ore',
      hint: 'Una trattativa in corso, oppure le ore che hai già lavorato.',
      to: '/app/deal',
      canDo: true,
      done: value(deal) || value(ore),
    },
    {
      id: 'documento',
      title: 'La prima offerta',
      hint: 'Dal deal, «Crea documento»: il template «Offerta» è già pronto.',
      to: '/app/deal',
      canDo: true,
      done: value(documento),
    },
  ]
  const doneCount = list.filter((s) => s.done).length
  return {
    loading,
    steps: list,
    doneCount,
    allDone: doneCount === list.length,
    assistantConnected: value(token),
  }
}
