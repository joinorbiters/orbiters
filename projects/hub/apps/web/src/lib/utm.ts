/** The attribution the page's own URL carries, if any: the five standard UTM keys and
 *  `utm_id`, which LinkedIn fills with the ad set. Read once, sent as they arrived --
 *  an unexpanded macro is stored as the literal it was, because that is what happened. */
export const UTM_KEYS = [
  'utm_source',
  'utm_medium',
  'utm_campaign',
  'utm_content',
  'utm_term',
  'utm_id',
] as const

export type Utm = Partial<Record<(typeof UTM_KEYS)[number], string>>

/** Where the landing (`projects/website/src/landing.js`) leaves the campaign for the
 *  tab, and where this app leaves what it read, so a detour through the chooser or a
 *  reload of the wizard without the query string still knows where the person came
 *  from (ORB-166). Session storage: it dies with the tab and holds only the campaign. */
export const UTM_STORAGE_KEY = 'orbiters.utm'

export function readUtm(search: string): Utm {
  const params = new URLSearchParams(search)
  const utm: Utm = {}
  for (const key of UTM_KEYS) {
    const value = params.get(key)?.trim().slice(0, 200)
    if (value) utm[key] = value
  }
  return utm
}

function storage(): Storage | null {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

/** What the tab remembers, if anything readable. */
export function recallUtm(): Utm {
  const raw = storage()?.getItem(UTM_STORAGE_KEY)
  return raw ? readUtm(`?${raw}`) : {}
}

/** Remember a non-empty attribution for the tab; a storage that refuses is not an error. */
export function rememberUtm(utm: Utm): void {
  if (Object.keys(utm).length === 0) return
  try {
    storage()?.setItem(UTM_STORAGE_KEY, new URLSearchParams(utm).toString())
  } catch {
    /* refused: the URL still has it, or nothing does */
  }
}

/** The attribution to send with an application: the URL's own keys when it has any,
 *  remembered for the tab; otherwise what the tab remembers from the landing or from
 *  an earlier page of this app. */
export function resolveUtm(search: string): Utm {
  const own = readUtm(search)
  if (Object.keys(own).length > 0) {
    rememberUtm(own)
    return own
  }
  return recallUtm()
}
