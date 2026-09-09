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

  // The community page on a phone (ORB-18): the box on the grid, equal gaps either side
  // of it once the shadow is counted, whole tiles at both edges, and no sideways scroll.
  // Three widths rather than one, because the slack a viewport leaves over the cell is
  // different at each and the arithmetic has to hold for all of them.
  for (const width of [360, 390, 430]) {
    test.describe(`the community page at ${width} wide`, () => {
      test.use({ viewport: { width, height: 844 }, deviceScaleFactor: 1 })

      test('sits on its grid', async ({ page }) => {
        await page.goto('/orbiters', { waitUntil: 'networkidle' })
        const m = await page.evaluate(() => {
          const cell = parseFloat(
            getComputedStyle(document.documentElement).getPropertyValue('--orb-cell'),
          )
          const origin = parseFloat(getComputedStyle(document.body).backgroundPositionX)
          const box = document.querySelector('.box') as HTMLElement
          const rect = box.getBoundingClientRect()
          const step = parseFloat(getComputedStyle(box).boxShadow.match(/(-?[\d.]+)px/)?.[1] ?? '')
          const h1 = document.querySelector('h1') as HTMLElement
          const range = document.createRange()
          range.selectNodeContents(h1)
          const lines = [...range.getClientRects()].map((line) => line.width)
          // Which CSS-pixel columns of the canvas carry any paint at all.
          const canvas = document.getElementById('field') as HTMLCanvasElement
          const ctx = canvas.getContext('2d') as CanvasRenderingContext2D
          const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height)
          const painted: number[] = []
          for (let x = 0; x < canvas.width; x += 1) {
            for (let y = 0; y < canvas.height; y += 1) {
              if ((data[(y * canvas.width + x) * 4 + 3] ?? 0) > 0) {
                painted.push(x)
                break
              }
            }
          }
          return {
            innerWidth: window.innerWidth,
            scrollWidth: document.documentElement.scrollWidth,
            cell,
            origin,
            step,
            left: rect.left,
            right: rect.right,
            lines,
            firstPainted: Math.min(...painted),
            lastPainted: Math.max(...painted) + 1,
          }
        })
        expect(m.scrollWidth).toBe(m.innerWidth)
        expect(m.cell).toBe(14)
        // The grid is centred: what the cell does not divide is split between the edges.
        expect(m.origin).toBe(Math.floor((m.innerWidth % m.cell) / 2))
        // Both borders of the box on grid lines, one whole column in from the left.
        expect(m.left).toBe(m.origin + m.cell)
        expect((m.right - m.origin) % m.cell).toBe(0)
        // The shadow is one cell, and what is left on the right after it is what is on
        // the left, give or take the odd pixel of slack.
        expect(m.step).toBe(m.cell)
        const gapRight = m.innerWidth - m.right - m.step
        expect(Math.abs(gapRight - m.left)).toBeLessThanOrEqual(1)
        // Tiles: painted inside the first grid line and never past the last whole cell.
        // A tile is inset one pixel in its cell, so the first paint is origin + 1 and
        // the last is one short of a grid line.
        expect(m.firstPainted).toBe(m.origin + 1)
        expect(m.lastPainted).toBeLessThanOrEqual(m.innerWidth)
        expect((m.lastPainted + 1 - m.origin) % m.cell).toBe(0)
        // The title wraps to two lines of comparable length, never a word alone.
        expect(m.lines).toHaveLength(2)
        expect(Math.min(...m.lines) / Math.max(...m.lines)).toBeGreaterThan(0.5)
      })
    })
  }

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
