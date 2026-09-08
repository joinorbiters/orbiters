import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: /landing-served\.spec\.ts$/,
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? 'github' : 'list',
  // The compose file publishes web on 127.0.0.1:8080 (docker-compose.yml).
  use: {
    baseURL: process.env.PIGROCRM_COMPOSE_URL ?? 'http://127.0.0.1:8080',
    trace: 'on-first-retry',
    ...devices['Desktop Chrome'],
  },
  expect: { timeout: 8_000 },
  // No webServer: this config deliberately does not own the stack. e2e-compose.sh
  // brings it up and tears it down, so a half-built image fails the script rather
  // than timing out inside Playwright with no logs.
})
