/**
 * Where the sidebar remembers which groups you left open.
 *
 * Its own module rather than a second export from `AppShell.tsx`, for the same reason
 * `features/settings/tabs.ts` is one: a component file that also exports plain values trips
 * `react-refresh/only-export-components`, and this is the kind of value a test wants to
 * name (`SIDEBAR_GROUPS_KEY`) rather than retype as a string literal.
 *
 * Collapsing the whole rail is deliberately *not* stored here: that is a per-visit
 * convenience (see `AppShell`), while an open group is a standing preference about the
 * shape of your own navigation.
 */
export const SIDEBAR_GROUPS_KEY = 'pigrocrm.sidebar.groups'

export type SidebarGroupState = Record<string, boolean>

/**
 * Reads the stored preference, tolerating everything storage can throw at us: a missing
 * key, text that is not JSON (hand-edited, or written by an older version), a JSON value
 * that is not an object, and `localStorage` itself being unavailable (Safari's private
 * mode throws on access, not on write). A sidebar that renders with every group closed is
 * a fine answer to any of those; an exception during render is not.
 */
export function readSidebarGroups(): SidebarGroupState {
  try {
    const raw = localStorage.getItem(SIDEBAR_GROUPS_KEY)
    if (!raw) return {}
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return {}
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).filter(
        ([, value]) => typeof value === 'boolean',
      ),
    ) as SidebarGroupState
  } catch {
    return {}
  }
}

export function writeSidebarGroups(state: SidebarGroupState): SidebarGroupState {
  try {
    localStorage.setItem(SIDEBAR_GROUPS_KEY, JSON.stringify(state))
  } catch {
    // A preference that cannot be stored is still a preference for this visit.
  }
  return state
}
