import { expect, test } from '@playwright/test'

/**
 * Runs against the real compose stack (nginx + api + db), never against the Vite
 * dev server. Spec 13, criterion 24: the routing this task changes lives in
 * deploy/nginx/spa.conf, which the dev server does not use at all -- so a suite
 * that only ever hits :5173 would pass while production 404s. Driven by
 * apps/web/scripts/e2e-compose.sh through playwright.compose.config.ts.
 */
test.describe('the served stack', () => {
  test('/ serves the landing, not the application', async ({ page }) => {
    const response = await page.goto('/')
    expect(response?.status()).toBe(200)
    await expect(page.locator('h1')).toHaveText('Il CRM che lavora al posto tuo.')
    await expect(page.locator('#root')).toHaveCount(0)
  })

  for (const path of ['/privacy', '/termini', '/orbiters']) {
    test(`${path} answers 200`, async ({ page }) => {
      expect((await page.goto(path))?.status()).toBe(200)
    })
  }

  test('/app/ serves the SPA', async ({ page }) => {
    await page.goto('/app/')
    await expect(page.locator('#root')).toHaveCount(1)
  })

  test('/app redirects to /app/, so the prefix location matches', async ({ page }) => {
    // Without `location = /app { return 302 /app/; }` the bare path does not enter
    // `location ^~ /app/` at all and falls through to the landing's `try_files`.
    await page.goto('/app')
    expect(new URL(page.url()).pathname).toBe('/app/')
  })

  test('a refresh on a deep link still serves the SPA shell', async ({ page }) => {
    const response = await page.goto('/app/clienti/00000000-0000-7000-8000-000000000000')
    expect(response?.status()).toBe(200)
    await expect(page.locator('#root')).toHaveCount(1)
  })

  test('the old /login link does not die', async ({ page }) => {
    await page.goto('/login')
    expect(new URL(page.url()).pathname).toBe('/app/login')
  })

  test('/health still reaches the API, unchanged by any of this', async ({ page }) => {
    const response = await page.request.get('/health')
    expect(response.status()).toBe(200)
    expect(await response.json()).toEqual({ status: 'ok' })
  })
})
