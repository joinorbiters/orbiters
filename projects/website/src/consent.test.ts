/* The cookie notice, driven in a DOM.
 *
 * The property that matters is not that a box appears: it is that **nothing is fetched
 * before somebody says yes**. So most of these tests assert the absence of a script
 * element, which is the only thing a visitor's browser would actually do differently.
 * `pixel.test.ts` holds the static half -- that no page carries a pixel of its own, so
 * this file is the whole of the gate.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

const js = readFileSync(join(__dirname, 'consent.js'), 'utf-8')
const SDK_URL = 'https://bzrcdn.openai.com/sdk/oaiq.min.js'
const KEY = 'orbiters.consent'

type Consent = {
  start: () => void
  decide: (decision: string, box?: Element | null) => void
  STORAGE_KEY: string
}

function run(): Consent {
  new Function(js)()
  return (window as unknown as { __consent: Consent }).__consent
}

function notice(): HTMLElement | null {
  return document.querySelector('.consent')
}

function sdkScripts(): HTMLScriptElement[] {
  return [...document.querySelectorAll('script')].filter((script) => script.src === SDK_URL)
}

function press(label: string): void {
  const button = [...document.querySelectorAll('.consent button')].find(
    (candidate) => candidate.textContent === label,
  )
  expect(button, `nessun bottone "${label}"`).toBeTruthy()
  ;(button as HTMLButtonElement).click()
}

beforeEach(() => {
  document.body.innerHTML = ''
  document.head.innerHTML = ''
  window.localStorage.clear()
  delete (window as unknown as { oaiq?: unknown }).oaiq
})

afterEach(() => {
  window.localStorage.clear()
})

describe('before anyone has decided', () => {
  it('shows one small notice and loads nothing', () => {
    run()
    expect(notice()).toBeTruthy()
    // The whole point. A snippet in the head with `consent(false)` after it would have
    // fetched this script anyway and handed OpenAI the visitor's IP.
    expect(sdkScripts()).toHaveLength(0)
    expect((window as unknown as { oaiq?: unknown }).oaiq).toBeUndefined()
  })

  it('asks in one sentence, and links the page that explains it', () => {
    run()
    const box = notice() as HTMLElement
    // Short is the requirement, not a sentence count: a notice nobody reads is a
    // notice that failed, and one that covers the page is worse than none.
    expect((box.textContent ?? '').length).toBeLessThan(130)
    expect(box.querySelector('a')?.getAttribute('href')).toBe('/privacy')
    expect(box.getAttribute('role')).toBe('region')
    expect(box.getAttribute('aria-label')).toBe('Cookie e misurazione')
  })

  it('offers a no as plainly as a yes', () => {
    // Both answers are one click from here. A notice whose only button is "accept" is
    // not a consent mechanism.
    run()
    const labels = [...document.querySelectorAll('.consent button')].map(
      (button) => button.textContent,
    )
    expect(labels).toEqual(['No', 'Va bene'])
  })
})

describe('once somebody accepts', () => {
  it('loads the SDK, initialises the pixel, and remembers the yes', () => {
    run()
    press('Va bene')

    const scripts = sdkScripts()
    expect(scripts).toHaveLength(1)
    expect(scripts[0]?.async).toBe(true)
    expect(window.localStorage.getItem(KEY)).toBe('granted')
    // The queue exists so a `measure` call made before the SDK arrives is not lost, and
    // the init is the first thing in it. Copied through `Array.from` because the stub
    // pushes the real `arguments` object, which `toEqual` does not consider an array,
    // and asserted whole so an empty queue fails here rather than on an index read.
    const queued = (window as unknown as { oaiq: { q: unknown[][] } }).oaiq.q
    expect(Array.from(queued[0] ?? [])).toEqual([
      'init',
      { pixelId: '9r6qrnPxBV8WDVGtpuaqxh', debug: true },
    ])
  })

  it('takes the notice away and does not ask again on the next page', () => {
    run()
    press('Va bene')
    expect(notice()).toBeNull()

    document.body.innerHTML = ''
    document.head.innerHTML = ''
    delete (window as unknown as { oaiq?: unknown }).oaiq
    run()
    expect(notice()).toBeNull()
    // And the pixel is there without being asked for a second time.
    expect(sdkScripts()).toHaveLength(1)
  })
})

describe('once somebody refuses', () => {
  it('loads nothing, and there is no oaiq for a signup to call', () => {
    run()
    press('No')

    expect(sdkScripts()).toHaveLength(0)
    expect((window as unknown as { oaiq?: unknown }).oaiq).toBeUndefined()
    expect(window.localStorage.getItem(KEY)).toBe('denied')
    expect(notice()).toBeNull()
  })

  it('does not come back, on this page or the next', () => {
    // A notice that reappears until it gets the answer it wants is a dark pattern with
    // a delay.
    run()
    press('No')
    document.body.innerHTML = ''
    run()
    expect(notice()).toBeNull()
    expect(sdkScripts()).toHaveLength(0)
  })
})

describe('when the browser refuses to remember anything', () => {
  it('still shows the notice and still honours the click', () => {
    // Safari in private mode, and any browser set to block site data, throw on
    // `localStorage` rather than returning null. A page that breaks there is worse than
    // one that asks again.
    const storage = window.localStorage
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      get() {
        throw new Error('site data bloccati')
      },
    })
    try {
      run()
      expect(notice()).toBeTruthy()
      press('Va bene')
      expect(sdkScripts()).toHaveLength(1)
    } finally {
      Object.defineProperty(window, 'localStorage', { configurable: true, value: storage })
    }
  })
})
