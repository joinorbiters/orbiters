# @orbiters/analytics

The one PostHog project every Orbiters surface reports to, and the policy the two
SPAs initialise it with. Design: `docs/design/2026-09-12-posthog-analytics-design.md`.

| File | What it holds | Who reads it |
|---|---|---|
| `posthog.ts` | The project key, the EU ingestion and asset hosts, which hostnames are silent (localhost, the test runners) and which are internal (the previews) | The CRM and the hub through `browser.ts`; the website's `pixel.test.ts`, which compares the literals `consent.js` carries with these |
| `browser.ts` | `initAnalytics`, `identifyUser`, `identifyGroup`, `capture`, `resetUser` on top of `posthog-js`: pageviews on history change, autocapture, replay with inputs masked (and every text, for the CRM), anonymous until a login, no-ops when the page is silent | `projects/pigrocrm/apps/web/src/main.tsx`, `projects/hub/apps/web/src/main.tsx` |

## Why a package rather than a constant in each project

A visitor of joinorbiters.com who later opens a space on pigro.joinorbiters.com is one
person only if both surfaces write to one project with one key. Two copies of that key
are the drift `shared/` exists to prevent, and the init policy (what is masked, what is
internal, what is silent) is a rule about the person being measured, not about one app.

## What is public and what is not

The project key (`phc_...`) is public: it is in every bundle and can only write events.
A personal API key (`phx_...`) writes to the whole account and belongs in no file of
this repository. `posthog.test.ts` refuses a `phx_` here.

## The website does not import this

`projects/website` injects PostHog's loader from `consent.js`, after the visitor's yes,
with no bundler dependency, so it repeats the key and the hosts as literals. Its
`pixel.test.ts` imports this package (a dev dependency) and fails when the two drift.
