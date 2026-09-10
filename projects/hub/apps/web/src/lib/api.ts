/**
 * The hub's HTTP client: plain `fetch`, same origin, cookies included. The API is a
 * handful of routes and three shapes, so a generated client would be more machinery
 * than code.
 *
 * Every failure becomes an `ApiError` carrying the status and, for a 422, the field
 * names FastAPI put in `detail[].loc`, which is what a wizard needs to point at the
 * right question rather than blame the whole form.
 */

import type { Utm } from './utm'

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly fields: string[] = [],
  ) {
    super(message)
  }
}

interface ValidationItem {
  loc?: unknown[]
  msg?: string
}

async function fail(response: Response): Promise<never> {
  let detail: unknown = null
  try {
    detail = (await response.json())?.detail
  } catch {
    detail = null
  }
  if (Array.isArray(detail)) {
    const items = detail as ValidationItem[]
    const fields = items.map((item) => String(item.loc?.at(-1) ?? '')).filter(Boolean)
    const message = items.map((item) => item.msg).filter(Boolean).join(' · ') || 'Dati non validi.'
    throw new ApiError(response.status, message, fields)
  }
  if (response.status === 429) {
    throw new ApiError(429, 'Troppe richieste da qui. Riprova tra un minuto.')
  }
  throw new ApiError(
    response.status,
    typeof detail === 'string' ? detail : `Qualcosa è andato storto (${response.status}).`,
  )
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { credentials: 'same-origin', ...init })
  if (!response.ok) await fail(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

// ---- the two wizards ------------------------------------------------------------------

export type Remoto = 'remoto' | 'ibrido' | 'in_sede'

export interface FreelancerApplication {
  nome: string
  cognome: string
  email: string
  linkedin_url: string
  tariffa_giornaliera: string
  posizione: string
  remoto: Remoto | ''
  links: string[]
  cv: File | null
}

/** Multipart, because the CV is a file. Empty optional fields are left out rather than
 *  sent as `""`, which the API would try to validate as a value. */
export function applyAsFreelancer(data: FreelancerApplication, utm: Utm): Promise<{ ok: true }> {
  const form = new FormData()
  form.set('nome', data.nome)
  form.set('cognome', data.cognome)
  form.set('email', data.email)
  form.set('tariffa_giornaliera', data.tariffa_giornaliera)
  form.set('posizione', data.posizione)
  form.set('remoto', data.remoto)
  if (data.linkedin_url.trim()) form.set('linkedin_url', data.linkedin_url.trim())
  for (const link of data.links) if (link.trim()) form.append('links', link.trim())
  for (const [key, value] of Object.entries(utm)) if (value) form.set(key, value)
  if (data.cv) form.set('cv', data.cv, data.cv.name)
  return request('/api/hub/freelancers', { method: 'POST', body: form })
}

export interface CompanyRequest {
  nome_azienda: string
  referente: string
  email: string
  progetto: string
  periodo_da: string
  durata: string
  budget_giornaliero: string
}

export function requestPeople(data: CompanyRequest, utm: Utm): Promise<{ ok: true }> {
  return request('/api/hub/companies', json({ ...data, utm: Object.keys(utm).length ? utm : null }))
}

// ---- the admin area -------------------------------------------------------------------

export interface Admin {
  id: string
  email: string
  nome: string
}

export interface Freelancer {
  id: string
  nome: string
  cognome: string
  email: string
  linkedin_url: string | null
  cv_filename: string
  cv_size: number
  tariffa_giornaliera: string
  posizione: string
  remoto: Remoto
  links: string[]
  stato: 'nuovo' | 'contattato' | 'attivo' | 'scartato'
  note: string | null
  utm_source: string | null
  utm_campaign: string | null
  created_at: string
  /** The thread, newest first. The detail carries it; the list leaves it empty. */
  commenti: Comment[]
}

export interface Company {
  id: string
  nome_azienda: string
  referente: string
  email: string
  progetto: string
  periodo_da: string
  durata: string
  budget_giornaliero: string
  stato: 'nuovo' | 'contattato' | 'in_corso' | 'chiuso'
  note: string | null
  utm_source: string | null
  created_at: string
  commenti: Comment[]
}

/** One remark in a row's thread: appended, signed and dated, never edited. */
export interface Comment {
  id: string
  entity_type: 'freelancer' | 'company'
  entity_id: string
  testo: string
  autore: string
  created_at: string
}

/** The two rows a thread can hang on, as the API paths name them. */
export type CommentKind = 'freelancers' | 'companies'

export interface Signup {
  id: string
  email: string
  nome: string | null
  cognome: string | null
  linkedin_url: string | null
  utm_source: string | null
  created_at: string
}

export const admin = {
  login: (email: string, password: string) =>
    request<Admin>('/api/hub/auth/login', json({ email, password })),
  logout: () => request<void>('/api/hub/auth/logout', { method: 'POST' }),
  me: () => request<Admin>('/api/hub/auth/me'),
  freelancers: (stato?: string) =>
    request<{ totale: number; items: Freelancer[] }>(
      `/api/hub/freelancers?limit=500${stato ? `&stato=${encodeURIComponent(stato)}` : ''}`,
    ),
  freelancer: (id: string) => request<Freelancer>(`/api/hub/freelancers/${id}`),
  cvUrl: (id: string) => `/api/hub/freelancers/${id}/cv`,
  moveFreelancer: (id: string, stato: string, note: string | null) =>
    request<Freelancer>(`/api/hub/freelancers/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stato, note }),
    }),
  companies: (stato?: string) =>
    request<{ totale: number; items: Company[] }>(
      `/api/hub/companies?limit=500${stato ? `&stato=${encodeURIComponent(stato)}` : ''}`,
    ),
  company: (id: string) => request<Company>(`/api/hub/companies/${id}`),
  moveCompany: (id: string, stato: string, note: string | null) =>
    request<Company>(`/api/hub/companies/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stato, note }),
    }),
  signups: () => request<{ totale: number; iscrizioni: Signup[] }>('/api/hub/signups?limit=500'),
  comments: (kind: CommentKind, id: string) =>
    request<Comment[]>(`/api/hub/${kind}/${id}/comments`),
  /** The author is the session's, so the body is the text alone. */
  addComment: (kind: CommentKind, id: string, testo: string) =>
    request<Comment>(`/api/hub/${kind}/${id}/comments`, json({ testo })),
}

// ---- the member area ------------------------------------------------------------------

/** The row as its owner reads it: what they gave, never the admin's fields. */
export interface MemberProfile {
  id: string
  nome: string
  cognome: string
  email: string
  linkedin_url: string | null
  cv_filename: string
  cv_size: number
  tariffa_giornaliera: string
  posizione: string
  remoto: Remoto
  links: string[]
  created_at: string
  updated_at: string
}

/** The seven answers a member may change. The email is not among them. */
export interface MemberUpdate {
  nome: string
  cognome: string
  linkedin_url: string | null
  tariffa_giornaliera: string
  posizione: string
  remoto: Remoto
  links: string[]
}

export const member = {
  /** 202 whether the address is known or not; the page says one thing in both cases. */
  requestLink: (email: string) => request<{ ok: true }>('/api/hub/auth/link', json({ email })),
  enter: (token: string) => request<MemberProfile>('/api/hub/auth/enter', json({ token })),
  me: () => request<MemberProfile>('/api/hub/me'),
  update: (data: MemberUpdate) =>
    request<MemberProfile>('/api/hub/me', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  replaceCv: (file: File) => {
    const form = new FormData()
    form.set('cv', file, file.name)
    return request<MemberProfile>('/api/hub/me/cv', { method: 'PUT', body: form })
  },
  cvUrl: '/api/hub/me/cv',
  logout: () => request<void>('/api/hub/me/logout', { method: 'POST' }),
}
