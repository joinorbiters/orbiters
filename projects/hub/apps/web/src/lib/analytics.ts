import { capture, identifyUser } from '@orbiters/analytics/browser'
import { useCallback, useEffect, useMemo, useRef } from 'react'
import type { Admin, MemberProfile } from './api'

/**
 * What the hub tells PostHog beyond pageviews and autocapture (ORB-185, design
 * `docs/design/2026-09-12-posthog-analytics-design.md` § The hub): the wizard funnel,
 * the guide download, and who the person is once a session is known. Every call goes
 * through `@orbiters/analytics/browser`, which is silent on localhost and in tests, so
 * nothing here checks whether analytics is on.
 */

export type WizardKind = 'freelance' | 'azienda'

/** `perk=` off a search string, as it arrived (trimmed and capped, the way `readUtm`
 *  keeps a UTM): the site's guide section sends `guida`, and a funnel needs the value
 *  that was there rather than the one the banner recognises. */
export function readPerkParam(search: string): string | null {
  const value = new URLSearchParams(search).get('perk')?.trim().slice(0, 200)
  return value || null
}

/**
 * The three funnel events of one wizard. `wizard_iniziato` once per mount, whatever
 * the page re-renders for; `onStep` for the engine to call on every step it shows,
 * including the first and the review (`passo === passi`), so a breakdown by `passo`
 * needs no special case; `completed` for the page to call once the API said yes.
 */
export function useWizardAnalytics(tipo: WizardKind, search: string) {
  const perk = readPerkParam(search)
  const base = useMemo(() => ({ tipo, ...(perk ? { perk } : {}) }), [tipo, perk])
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true
    capture('wizard_iniziato', base)
  }, [base])

  const onStep = useCallback(
    (passo: number, passi: number) => capture('wizard_passo', { ...base, passo, passi }),
    [base],
  )
  const completed = useCallback(() => capture('wizard_completato', base), [base])
  return { onStep, completed }
}

function useIdentify(
  person: Pick<Admin | MemberProfile, 'id' | 'email' | 'nome'> | null | undefined,
  ruolo?: 'admin',
): void {
  // Primitives rather than the object: the query hands a new object on every refetch
  // and the person has not changed.
  const id = person?.id
  const email = person?.email
  const nome = person?.nome
  useEffect(() => {
    if (id) identifyUser(id, { email, nome, ...(ruolo ? { ruolo } : {}) })
  }, [id, email, nome, ruolo])
}

/** The freelancer behind the member cookie, once `useMember` has one. */
export function useIdentifyMember(profile: MemberProfile | null | undefined): void {
  useIdentify(profile)
}

/** The admin behind the admin cookie, once `useAdmin` has one. */
export function useIdentifyAdmin(admin: Admin | null | undefined): void {
  useIdentify(admin, 'admin')
}
