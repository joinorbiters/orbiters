/**
 * The one PostHog project every Orbiters surface reports to.
 *
 * The project key is public by design: it ends up in every bundle and in every page
 * that measures, and it can only write events into this project. It is committed here
 * for the same reason the ChatGPT Ads pixel id is committed in the website's
 * `consent.js`: it is a value every surface must agree on, and a copy per project is
 * the drift `shared/` exists to prevent. A *personal* API key (`phx_...`) is a
 * different thing, with write access to the whole account, and belongs nowhere in the
 * repository.
 *
 * The website cannot import this module at runtime (it injects PostHog's loader from
 * `consent.js`, after consent, with no bundler dependency), so it carries the key and
 * the hosts as literals and `pixel.test.ts` compares them with these.
 */

/** Cloud EU: events stay in Europe. */
export const POSTHOG_HOST = 'https://eu.i.posthog.com'
/** Where the browser SDK and the recorder are fetched from, EU as well. */
export const POSTHOG_ASSET_HOST = 'https://eu-assets.i.posthog.com'
export const POSTHOG_KEY = 'phc_BEfHvXF3DHU4ZGrJc9QJFPDrR2PxXuGDnZL4Kf6XabLb'

/**
 * The hosts whose events are marked as internal rather than dropped: the two preview
 * stacks. A preview is where a change is looked at before a tag, and its clicks would
 * otherwise read as customers.
 */
export const INTERNAL_HOSTS = /^preview\./

/**
 * The hosts that send nothing at all: a developer's machine and every test runner
 * (jsdom's default location is `localhost`). Decided on the hostname alone, so a
 * build carries no environment flag and the same bundle behaves the same everywhere.
 */
const SILENT_HOSTS = new Set(['', 'localhost', '127.0.0.1', '[::1]', '0.0.0.0'])

export function analyticsEnabled(hostname: string): boolean {
  return !SILENT_HOSTS.has(hostname)
}

export function isInternalHost(hostname: string): boolean {
  return INTERNAL_HOSTS.test(hostname)
}
