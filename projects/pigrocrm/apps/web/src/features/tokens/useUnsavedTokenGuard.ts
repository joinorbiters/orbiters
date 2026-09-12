import { useBlocker } from '@tanstack/react-router'

/**
 * A freshly minted token is on screen exactly once. Leaving the page while it is there --
 * by a Link, by Back, by a reload or by closing the tab -- loses it for good, so every
 * surface that reveals one asks the same question first. Shared between the Token page
 * and the «Collega un agente» dialog so the two cannot drift.
 */
export const LEAVE_WARNING =
  'Il token mostrato non è stato confermato come copiato: se esci ora sparisce per sempre e dovrai revocarlo e crearne uno nuovo. Uscire comunque?'

export function confirmDiscardingToken(): boolean {
  return window.confirm(LEAVE_WARNING)
}

/** Escape and click-outside are the dialog's own business; this covers the two ways those
 *  do not: an in-app route change (`useBlocker`) and a real reload or close
 *  (`enableBeforeUnload`, the native "leave site?" prompt). Both can be declined. */
export function useUnsavedTokenGuard(issued: boolean): void {
  useBlocker({
    shouldBlockFn: () => issued && !confirmDiscardingToken(),
    enableBeforeUnload: issued,
  })
}
