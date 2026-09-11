import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

/**
 * landing.js carries the campaign a visitor landed with into the hub (ORB-166): the
 * six UTM keys go onto every link into `/hub/`, nothing else is touched, and the same
 * keys are remembered for the tab under the key the hub reads.
 */
const source = readFileSync(join(__dirname, 'landing.js'), 'utf-8')

interface Landing {
  carryUtm: (root?: ParentNode, search?: string) => number
  readUtm: (search: string) => URLSearchParams
  UTM_KEYS: readonly string[]
  UTM_STORAGE_KEY: string
}

function load(): Landing {
  new Function(source)()
  const api = (window as Window & { __landing?: Landing }).__landing
  if (!api) throw new Error('landing.js did not expose window.__landing')
  return api
}

function fixture(hrefs: string[]) {
  const root = document.createElement('div')
  root.innerHTML = hrefs.map((href) => `<a href="${href}">x</a>`).join('')
  return root
}

const hrefsOf = (root: ParentNode) => [...root.querySelectorAll('a')].map((a) => a.getAttribute('href'))

beforeEach(() => window.sessionStorage.clear())
afterEach(() => window.sessionStorage.clear())

describe('carryUtm', () => {
  it('appends the UTM keys of the page to every link into the hub, and to nothing else', () => {
    const landing = load()
    const root = fixture(['/hub/freelance', '/hub/aziende', '/hub/freelance?perk=guida', '/privacy', 'https://pigro.joinorbiters.com/app/'])
    const rewritten = landing.carryUtm(root, '?utm_source=linkedin&utm_campaign=orbita&utm_id=42&gclid=nope&utm_term=%20')
    expect(rewritten).toBe(3)
    expect(hrefsOf(root)).toEqual([
      '/hub/freelance?utm_source=linkedin&utm_campaign=orbita&utm_id=42',
      '/hub/aziende?utm_source=linkedin&utm_campaign=orbita&utm_id=42',
      '/hub/freelance?perk=guida&utm_source=linkedin&utm_campaign=orbita&utm_id=42',
      '/privacy',
      'https://pigro.joinorbiters.com/app/',
    ])
  })

  it('remembers the keys for the tab under the name the hub reads', () => {
    const landing = load()
    landing.carryUtm(fixture(['/hub/freelance']), '?utm_source=linkedin&utm_medium=paid')
    expect(landing.UTM_STORAGE_KEY).toBe('orbiters.utm')
    expect(window.sessionStorage.getItem('orbiters.utm')).toBe('utm_source=linkedin&utm_medium=paid')
  })

  it('never overrides a key a link already carries', () => {
    const landing = load()
    const root = fixture(['/hub/freelance?utm_source=newsletter'])
    landing.carryUtm(root, '?utm_source=linkedin&utm_campaign=orbita')
    expect(hrefsOf(root)).toEqual(['/hub/freelance?utm_source=newsletter&utm_campaign=orbita'])
  })

  it('leaves the page alone when it was opened without a campaign', () => {
    const landing = load()
    const root = fixture(['/hub/freelance', '/hub/aziende'])
    expect(landing.carryUtm(root, '?ref=friend')).toBe(0)
    expect(hrefsOf(root)).toEqual(['/hub/freelance', '/hub/aziende'])
    expect(window.sessionStorage.getItem('orbiters.utm')).toBeNull()
  })

  it('caps a value at 200 characters, like the hub does', () => {
    const landing = load()
    const long = 'x'.repeat(250)
    expect(landing.readUtm(`?utm_content=${long}`).get('utm_content')).toHaveLength(200)
  })
})
