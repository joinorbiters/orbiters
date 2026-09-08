import { useCallback, useSyncExternalStore } from 'react'

/**
 * Whether a CSS media query matches, as a value React can render.
 *
 * `useSyncExternalStore` rather than `useState` + `useEffect`: the viewport is an external
 * store, this is what that hook is for, and it avoids the extra render (and the
 * `react-hooks/set-state-in-effect` warning) that the state-in-an-effect shape carries.
 * The server snapshot is `false`, so anything rendered without a window gets the
 * small-screen answer -- the layout that needs no measurement to be usable.
 *
 * Used by `AppShell` for the one thing CSS cannot express here: below `lg` the sidebar is
 * a rail whose expanded form is an overlay, which is a different *structure*, not a
 * different width.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onStoreChange: () => void) => {
      if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
        return () => {}
      }
      const list = window.matchMedia(query)
      list.addEventListener('change', onStoreChange)
      return () => list.removeEventListener('change', onStoreChange)
    },
    [query],
  )

  const getSnapshot = useCallback(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
    return window.matchMedia(query).matches
  }, [query])

  return useSyncExternalStore(subscribe, getSnapshot, () => false)
}
