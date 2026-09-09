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

export function readUtm(search: string): Utm {
  const params = new URLSearchParams(search)
  const utm: Utm = {}
  for (const key of UTM_KEYS) {
    const value = params.get(key)?.trim().slice(0, 200)
    if (value) utm[key] = value
  }
  return utm
}
