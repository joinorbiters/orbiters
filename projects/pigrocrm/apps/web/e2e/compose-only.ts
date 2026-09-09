/**
 * Which specs belong to the *composed* stack (nginx + api + db) rather than to `pnpm
 * dev`, declared once so the two Playwright configs cannot disagree about it.
 *
 * They disagreed for a day, and it cost seven red tests. `served.spec.ts` was called
 * `landing-served.spec.ts` until the public pages became their own project (2026-09-09);
 * `playwright.compose.config.ts` was updated to `testMatch: /served\.spec\.ts$/` and
 * `playwright.config.ts` was left ignoring `/landing.*\.spec\.ts$/`, a pattern that from
 * then on matched nothing. The dev-server run therefore picked up seven assertions about
 * `deploy/nginx/spa.conf` -- routing the dev server does not implement at all -- and
 * failed every one of them, for a reason that has nothing to do with the application.
 *
 * Not a `*.spec.ts` file, so Playwright's own glob never mistakes it for a suite with no
 * tests in it -- the same reason `helpers.ts` is spelled that way.
 */
export const COMPOSE_ONLY = /served\.spec\.ts$/
