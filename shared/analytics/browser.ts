/**
 * How the two SPAs (the CRM and the hub) initialise PostHog, once, and the four calls
 * they make afterwards. The policy lives here so the two cannot drift: pageviews on
 * history changes (both use TanStack Router), autocapture on, session replay with every
 * input masked, anonymous visitors kept anonymous until somebody logs in, preview
 * marked as internal, and nothing at all on localhost or under a test runner.
 *
 * Every wrapper is a no-op until `initAnalytics` has decided the page is measured, so a
 * feature can call `capture` unconditionally and a test never sees a network call.
 */
import posthog from 'posthog-js'
import { POSTHOG_HOST, POSTHOG_KEY, analyticsEnabled, isInternalHost } from './posthog'

export interface AnalyticsOptions {
  /**
   * Mask every text node in a recording, not only the inputs. The CRM sets this: a
   * replay must show where a person clicks and stops, never an invoice amount or a
   * customer's name. The hub's wizards are forms, so masking the inputs is enough.
   */
  maskText?: boolean
  /** The hostname to decide on; defaults to the page's own. Tests pass one. */
  hostname?: string
}

let active = false

/** Initialises PostHog and answers whether this page is measured at all. */
export function initAnalytics(options: AnalyticsOptions = {}): boolean {
  const hostname =
    options.hostname ?? (typeof window === 'undefined' ? '' : window.location.hostname)
  if (!analyticsEnabled(hostname)) {
    active = false
    return false
  }
  posthog.init(POSTHOG_KEY, {
    api_host: POSTHOG_HOST,
    defaults: '2026-08-30',
    person_profiles: 'identified_only',
    capture_pageview: 'history_change',
    autocapture: true,
    session_recording: {
      maskAllInputs: true,
      ...(options.maskText ? { maskTextSelector: '*' } : {}),
    },
  })
  // Called rather than configured: `internal_or_test_user_hostname` exists as an
  // option, but it did not take effect when tried live against array.js 1.430.2 on
  // 2026-09-12 (the running config still showed the SDK's own default for it, and the
  // events arrived unmarked). The explicit call is what the option ends up making.
  if (isInternalHost(hostname)) posthog.setInternalOrTestUser()
  active = true
  return true
}

/** True once `initAnalytics` decided this page sends events. */
export function analyticsActive(): boolean {
  return active
}

export function identifyUser(id: string, properties?: Record<string, unknown>): void {
  if (active) posthog.identify(id, properties)
}

export function identifyGroup(
  type: string,
  key: string,
  properties?: Record<string, unknown>,
): void {
  if (active) posthog.group(type, key, properties)
}

export function capture(event: string, properties?: Record<string, unknown>): void {
  if (active) posthog.capture(event, properties)
}

/** Forgets the person: called on logout, before the page leaves. */
export function resetUser(): void {
  if (active) posthog.reset()
}

/** For tests only: back to the state before `initAnalytics`. */
export function __resetAnalyticsForTests(): void {
  active = false
}
