/**
 * The stopwatch's arithmetic, kept out of the component file so `TimerBar.tsx` exports
 * a component and nothing else (eslint's `react-refresh/only-export-components`).
 */

/** `01:23:45` from a number of seconds. Hours are not capped at 24 on purpose: a timer
 *  forgotten over a weekend should read as the alarming figure it is. */
export function formatElapsed(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds))
  const h = Math.floor(whole / 3600)
  const m = Math.floor((whole % 3600) / 60)
  const s = whole % 60
  return [h, m, s].map((part) => String(part).padStart(2, '0')).join(':')
}

/** Seconds since the server's `started_at`, at the instant `now` (ms since the epoch). */
export function elapsedSince(startedAt: string, now: number): number {
  return (now - new Date(startedAt).getTime()) / 1000
}
