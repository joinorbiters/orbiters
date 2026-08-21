import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const source = readFileSync(join(__dirname, 'reveal.js'), 'utf-8')

interface RevealWindow {
  __pigroReveal?: (doc: Document) => void
}

/** Evaluates reveal.js the way the browser does: as a classic script that assigns
 *  onto `window`. No bundler and no import, because the shipped file has none. */
function load(): (doc: Document) => void {
  new Function('window', 'document', 'IntersectionObserver', source)(
    window,
    document,
    window.IntersectionObserver,
  )
  const entry = (window as unknown as RevealWindow).__pigroReveal
  if (!entry) throw new Error('reveal.js did not expose window.__pigroReveal')
  return entry
}

describe('reveal.js', () => {
  beforeEach(() => {
    document.body.innerHTML = '<p class="rise">uno</p><p class="rise">due</p><p>tre</p>'
    delete (window as unknown as RevealWindow).__pigroReveal
  })

  it('is small enough to be worth having', () => {
    // "roughly a kilobyte" from spec 9.4, made checkable. The whole page budget is
    // 40 KB; a reveal script that grew past 2 KB stopped being this script.
    expect(Buffer.byteLength(source, 'utf-8')).toBeLessThan(2048)
  })

  it('makes no request and touches no global other than window and document', () => {
    expect(source).not.toMatch(/fetch\(|XMLHttpRequest|import\s|require\(/)
    expect(source).not.toMatch(/localStorage|sessionStorage|document\.cookie|navigator\.sendBeacon/)
  })

  it('hides the elements it is about to reveal, and only those', () => {
    load()(document)
    const risen = [...document.querySelectorAll('.rise')]
    expect(risen.every((element) => element.hasAttribute('data-hidden'))).toBe(true)
    expect(document.querySelector('p:not(.rise)')?.hasAttribute('data-hidden')).toBe(false)
  })

  it('numbers them so the CSS can stagger them', () => {
    load()(document)
    const risen = [...document.querySelectorAll<HTMLElement>('.rise')]
    expect(risen[0]?.style.getPropertyValue('--rise-index')).toBe('0')
    expect(risen[1]?.style.getPropertyValue('--rise-index')).toBe('1')
  })

  it('reveals an element when the observer reports it visible, and stops watching it', () => {
    const unobserve = vi.fn()
    let notify: ((entries: { target: Element; isIntersecting: boolean }[]) => void) | undefined
    vi.stubGlobal(
      'IntersectionObserver',
      class {
        constructor(callback: (entries: { target: Element; isIntersecting: boolean }[]) => void) {
          notify = callback
        }
        observe = vi.fn()
        unobserve = unobserve
        disconnect = vi.fn()
      },
    )

    load()(document)
    const first = document.querySelector('.rise')!
    notify?.([{ target: first, isIntersecting: true }])

    expect(first.hasAttribute('data-hidden')).toBe(false)
    expect(unobserve).toHaveBeenCalledWith(first)
    vi.unstubAllGlobals()
  })

  it('leaves everything visible when IntersectionObserver does not exist', () => {
    // The rule that matters, restated as a test: no browser, and no failure mode,
    // may produce a blank page. If the mechanism is missing, so is the animation --
    // never the content.
    vi.stubGlobal('IntersectionObserver', undefined)
    load()(document)
    expect([...document.querySelectorAll('.rise')].some((e) => e.hasAttribute('data-hidden'))).toBe(
      false,
    )
    vi.unstubAllGlobals()
  })

  it('does not hide anything when the reader asked for reduced motion', () => {
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: query.includes('prefers-reduced-motion'),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }))
    load()(document)
    expect([...document.querySelectorAll('.rise')].some((e) => e.hasAttribute('data-hidden'))).toBe(
      false,
    )
    vi.unstubAllGlobals()
  })
})
