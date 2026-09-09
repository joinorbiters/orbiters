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
      // landing-served.spec.ts runs against the composed stack, through
      // playwright.compose.config.ts, never against `pnpm dev`.
      testIgnore: /landing.*\.spec\.ts$/,
      use: { ...devices['Desktop Chrome'], baseURL: 'http://localhost:5173' },
    },
  ],
  webServer: {
    command: 'pnpm dev',
    url: 'http://localhost:5173/app/',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
})
