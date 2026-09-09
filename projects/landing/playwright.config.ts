import { defineConfig, devices } from '@playwright/test'

// The landing is four static pages: the suite drives a real browser against the built
// output, served exactly as `vite preview` serves it, which is the closest thing to
// production this project can run on its own. The API proxy in vite.config.ts is what
// lets the Orbiters form be exercised without the CRM's stack; the specs that need it
// stub the response.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: { ...devices['Desktop Chrome'], baseURL: 'http://localhost:4173', trace: 'on-first-retry' },
  expect: { timeout: 8_000 },
  webServer: {
    // `preview` serves `dist`, so the build has to have happened first. Chaining it
    // here keeps the documented command a single one.
    command: 'pnpm build && pnpm preview',
    url: 'http://localhost:4173/',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
