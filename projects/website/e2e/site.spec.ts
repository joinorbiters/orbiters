import { expect, test } from '@playwright/test'

const PAGES = ['/', '/privacy', '/termini', '/orbiters'] as const
const BUDGET_BYTES = 40 * 1024
// The one host these pages are allowed to talk to besides their own, and only from the
// two an ad can land on: the ChatGPT Ads measurement SDK, injected by the snippet in
// their head. `src/pixel.test.ts` owns which pages declare it; this file is what proves
// that the browser really does ask for nothing else.
const PIXEL_HOST = 'bzrcdn.openai.com'
const MEASURED_PATHS = new Set(['/', '/orbiters'])

test.describe('every page of the site', () => {
  for (const path of PAGES) {
    test(`${path} asks nothing of any host it has not declared`, async ({ page }) => {
      // Every request is collected unconditionally, and only classified as
      // "foreign" once navigation has actually resolved: the very first
      // `request` event IS the navigation to `path` itself, and page.url()
      // still reads as about:blank while it is in flight, so checking the
      // host inline as each event fires misclassifies the page's own load.
      const requested: string[] = []
      page.on('request', (request) => requested.push(request.url()))
      await page.goto(path)
      await page.waitForLoadState('networkidle')
      const host = new URL(page.url()).host
      const foreign = [...new Set(requested.map((url) => new URL(url).host))].filter(
        (requestedHost) => requestedHost !== host,
      )
      // Still a verification and not a promise, and still an exact list rather than an
      // allowance: the two pages an ad lands on may reach the measurement SDK's host
      // and nothing else, and the two legal pages may reach nobody. Before
      // 2026-09-09 every page reached nobody, and this assertion is where that stopped
      // being true -- so it names the one exception instead of being deleted.
      expect(foreign).toEqual(MEASURED_PATHS.has(path) ? [PIXEL_HOST] : [])
    })
  }

  test('loads cold under 40 KB, excluding the shared woff2 and the pixel SDK', async ({
    page,
  }) => {
    let bytes = 0
    page.on('requestfinished', async (request) => {
      if (request.url().endsWith('.woff2')) return
      // The measurement SDK is a third party's file, fetched from a third party's CDN:
      // its weight is not ours to control and counting it would make this budget a
      // report on OpenAI's build rather than on our page. What the budget exists for --
      // that the markup, the CSS and our own scripts stay small -- is unchanged, and
      // the SDK's presence at all is asserted above.
      if (new URL(request.url()).host === PIXEL_HOST) return
      const sizes = await request.sizes()
      bytes += sizes.responseBodySize + sizes.responseHeadersSize
    })
    await page.goto('/', { waitUntil: 'networkidle' })
    expect(bytes, `${bytes} bytes transferred`).toBeLessThan(BUDGET_BYTES)
  })

  test('shares exactly one font file with the app, from its own origin', async ({ page }) => {
    const fonts: string[] = []
    page.on('request', (request) => {
      if (request.url().endsWith('.woff2')) fonts.push(request.url())
    })
    await page.goto('/', { waitUntil: 'networkidle' })
    expect(fonts).toHaveLength(1)
    expect(fonts[0]).toContain('outfit-variable-latin')
  })

  test.describe('with JavaScript disabled', () => {
    test.use({ javaScriptEnabled: false })

    for (const path of PAGES) {
      test(`${path} shows all of its content and all of its links work`, async ({ page }) => {
        await page.goto(path)
        // Nothing on these pages is revealed by a script: every box, card and kicker
        // is visible on the first paint, and the same without any JavaScript at all.
        for (const selector of ['h1', '.box', '.card', '.kicker']) {
          const found = page.locator(selector)
          const count = await found.count()
          for (let index = 0; index < count; index += 1) {
            await expect(found.nth(index)).toBeVisible()
          }
        }
        await expect(page.locator('h1')).toBeVisible()
        for (const link of await page.locator('a[href^="/"]').all()) {
          const href = await link.getAttribute('href')
          expect(href).toBeTruthy()
          const response = await page.request.get(href!)
          expect(response.status(), `${href} from ${path}`).toBeLessThan(400)
        }
      })
    }
  })
})
