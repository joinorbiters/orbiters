import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'

const PAGES = ['/', '/pigrocrm', '/privacy', '/termini', '/orbiters'] as const
const BUDGET_BYTES = 40 * 1024
// The one host these pages may ever talk to besides their own: the ChatGPT Ads
// measurement SDK. "May ever" is the whole subtlety -- `consent.js` injects it only
// after a visitor has said yes, so with no decision stored no page requests it at all,
// which is what the first test below checks and the last one checks the other half of.
const PIXEL_HOST = 'bzrcdn.openai.com'
const CONSENT_KEY = 'orbiters.consent'
// The two pages that carry the notice, and therefore the two that can end up with the
// pixel. `src/pixel.test.ts` owns which pages declare it.
const MEASURED_PATHS = ['/', '/pigrocrm', '/orbiters'] as const

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
      // Before 2026-09-09 every page reached nobody, and that is still true of a first
      // visit: the measurement SDK is not fetched until the notice is answered, so a
      // page that requested it here would mean the consent gate is not a gate.
      expect(foreign).toEqual([])
    })
  }

  test('loads cold under 40 KB, excluding the shared woff2 and the pixel SDK', async ({
    page,
  }) => {
    let bytes = 0
    page.on('requestfinished', async (request) => {
      if (request.url().endsWith('.woff2')) return
      // Belt and braces: a first visit does not fetch the SDK at all (the notice has
      // not been answered), so this branch only matters if somebody runs this test with
      // consent already stored. Either way the weight of a third party's file is not
      // ours to control, and counting it would make this budget a report on OpenAI's
      // build rather than on our page.
      if (new URL(request.url()).host === PIXEL_HOST) return
      const sizes = await request.sizes()
      bytes += sizes.responseBodySize + sizes.responseHeadersSize
    })
    await page.goto('/', { waitUntil: 'networkidle' })
    expect(bytes, `${bytes} bytes transferred`).toBeLessThan(BUDGET_BYTES)
  })

  for (const path of MEASURED_PATHS) {
    test(`${path} shows the notice, and loads the pixel only once it is accepted`, async ({
      page,
    }) => {
      const requested: string[] = []
      page.on('request', (request) => requested.push(request.url()))
      await page.goto(path)
      await page.waitForLoadState('networkidle')

      const notice = page.locator('.consent')
      await expect(notice).toBeVisible()
      // Nothing has been fetched from OpenAI while the question is still open.
      expect(requested.filter((url) => new URL(url).host === PIXEL_HOST)).toEqual([])
      // And both answers are one click away, which is what makes it a consent notice.
      await expect(notice.getByRole('button', { name: 'No' })).toBeVisible()

      await notice.getByRole('button', { name: 'Va bene' }).click()
      await expect(notice).toBeHidden()
      // The request really does leave now -- the SDK's host is unreachable from CI, so
      // what is asserted is the attempt, not a 200.
      await expect
        .poll(() => requested.filter((url) => new URL(url).host === PIXEL_HOST).length)
        .toBeGreaterThan(0)
    })

    test(`${path} asks nothing of OpenAI after a refusal, and does not ask again`, async ({
      page,
    }) => {
      const requested: string[] = []
      page.on('request', (request) => requested.push(request.url()))
      await page.goto(path)
      await page.locator('.consent').getByRole('button', { name: 'No' }).click()
      await page.reload()
      await page.waitForLoadState('networkidle')

      // A notice that comes back until it gets the answer it wants is a dark pattern
      // with a delay.
      await expect(page.locator('.consent')).toHaveCount(0)
      expect(requested.filter((url) => new URL(url).host === PIXEL_HOST)).toEqual([])
      expect(await page.evaluate((key) => localStorage.getItem(key), CONSENT_KEY)).toBe('denied')
    })
  }

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
          // `/hub/` is the Orbiters hub (projects/hub), another deployable on the same
          // origin: the host's nginx sends it there, the preview server here has nothing
          // behind it. The link is verified where it resolves, not here.
          if (href!.startsWith('/hub/')) continue
          const response = await page.request.get(href!)
          expect(response.status(), `${href} from ${path}`).toBeLessThan(400)
        }
      })
    }
  })
})

// The preview server is what this suite drives, and until ORB-21 it served PigroCRM's
// page at `/` and a 200 for any path at all, so a test written against `/` checked a
// page production never serves there. These pin the served map to deploy/nginx.conf's:
// the same file under each name, the same redirect, and a 404 where nginx has one.
test.describe('the path map, as production serves it', () => {
  const source = (name: string) =>
    readFileSync(new URL(`../src/${name}`, import.meta.url), 'utf-8').match(/<title>([^<]+)<\/title>/)?.[1]

  test('/ is the community page and /pigrocrm is the landing', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveTitle(source('orbiters.html')!)
    await page.goto('/pigrocrm')
    await expect(page).toHaveTitle(source('index.html')!)
  })

  test('/orbiters is a 301 to /', async ({ page }) => {
    const response = await page.request.get('/orbiters', { maxRedirects: 0 })
    expect(response.status()).toBe(301)
    expect(response.headers()['location']).toBe('/')
  })

  for (const path of ['/nonexistent', '/pigrocrm/', '/index.html', '/orbiters.html']) {
    test(`${path} is a 404, not the landing by fallback`, async ({ page }) => {
      const response = await page.goto(path)
      expect(response?.status()).toBe(404)
    })
  }
})

// The two policy pages are the two whose text column carries long unbreakable strings:
// the Gmail scopes on /privacy are read verbatim by Google's review and cannot be
// shortened. On 2026-09-09 that column was a grid whose one implicit track had grown to
// the widest of them, 452px on a 390px phone, and the page scrolled sideways (ORB-22).
// This asserts the symptom rather than the fix, so the next long string added to
// either page fails here instead of in a visitor's hand.
test.describe('the policy pages on a phone', () => {
  for (const width of [360, 390]) {
    for (const path of ['/privacy', '/termini'] as const) {
      test(`${path} does not scroll sideways at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 844 })
        await page.goto(path, { waitUntil: 'networkidle' })
        const measured = await page.evaluate(() => ({
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth,
        }))
        expect(
          measured.scrollWidth,
          `${path} at ${width}px: scrollWidth ${measured.scrollWidth}, clientWidth ${measured.clientWidth}`,
        ).toBe(measured.clientWidth)
      })
    }
  }
})
