import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false, // one database, shared state
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? 'github' : 'list',
  // A generous default: e2e/resilience.spec.ts kills the API and waits for
  // react-query's own retry policy (lib/query.ts: two retries with backoff on
  // anything that is not a 401/403) to give up before the error banner appears --
  // the library's own default 5s Playwright timeout can be tight for that one
  // assertion on a loaded CI box, and there is no cost to affording it everywhere
  // else.
  use: { trace: 'on-first-retry' },
  expect: { timeout: 8_000 },
  projects: [
    {
      name: 'chromium',
      testIgnore: /landing.*\.spec\.ts$/,
      use: { ...devices['Desktop Chrome'], baseURL: 'http://localhost:5173' },
    },
    {
      // The landing is a separate build served by a static server, so it needs its
      // own origin. Splitting by project rather than by baseURL override keeps the
      // app suite pointed at `pnpm dev` -- which now serves under /app/ -- without
      // either suite knowing about the other.
      name: 'landing',
      testMatch: /landing\.spec\.ts$/,
      use: { ...devices['Desktop Chrome'], baseURL: 'http://localhost:4173' },
    },
  ],
  webServer: [
    {
      command: 'pnpm dev',
      url: 'http://localhost:5173/app/',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      // `preview` serves dist-landing, so the build has to have happened. Chaining
      // it here means the E2E command stays the one documented command.
      command: 'pnpm build:landing && pnpm preview:landing',
      url: 'http://localhost:4173/',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
})
