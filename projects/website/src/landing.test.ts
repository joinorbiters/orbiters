import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

/**
 * landing.js carries where a visitor came from into the hub: the six UTM keys of the
 * page's URL (ORB-166) and the page itself as `da=` (ORB-167) go onto every link into
 * `/hub/`, nothing else is touched, and both are remembered for the tab under the keys
 * the hub reads.
 */
const source = readFileSync(join(__dirname, 'landing.js'), 'utf-8')

interface Landing {
  carryUtm: (root?: ParentNode, search?: string, pathname?: string) => number
  readUtm: (search: string) => URLSearchParams
  pageSlug: (pathname?: string) => string
  UTM_KEYS: readonly string[]
  UTM_STORAGE_KEY: string
  ORIGIN_STORAGE_KEY: string
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
  it('appends the UTM keys and the page to every link into the hub, and to nothing else', () => {
    const landing = load()
    const root = fixture(['/hub/freelance', '/hub/aziende', '/hub/freelance?perk=guida', '/privacy', 'https://pigro.joinorbiters.com/app/'])
    const rewritten = landing.carryUtm(root, '?utm_source=linkedin&utm_campaign=orbita&utm_id=42&gclid=nope&utm_term=%20', '/')
    expect(rewritten).toBe(3)
    expect(hrefsOf(root)).toEqual([
      '/hub/freelance?utm_source=linkedin&utm_campaign=orbita&utm_id=42&da=home',
      '/hub/aziende?utm_source=linkedin&utm_campaign=orbita&utm_id=42&da=home',
      '/hub/freelance?perk=guida&utm_source=linkedin&utm_campaign=orbita&utm_id=42&da=home',
      '/privacy',
      'https://pigro.joinorbiters.com/app/',
    ])
  })

  it('remembers the campaign and the page for the tab under the names the hub reads', () => {
    const landing = load()
    landing.carryUtm(fixture(['/hub/freelance']), '?utm_source=linkedin&utm_medium=paid', '/pigrocrm')
    expect(landing.UTM_STORAGE_KEY).toBe('orbiters.utm')
    expect(landing.ORIGIN_STORAGE_KEY).toBe('orbiters.da')
    expect(window.sessionStorage.getItem('orbiters.utm')).toBe('utm_source=linkedin&utm_medium=paid')
    expect(window.sessionStorage.getItem('orbiters.da')).toBe('pigrocrm')
  })

  it('never overrides a key a link already carries', () => {
    const landing = load()
    const root = fixture(['/hub/freelance?utm_source=newsletter&da=altro'])
    landing.carryUtm(root, '?utm_source=linkedin&utm_campaign=orbita', '/')
    expect(hrefsOf(root)).toEqual(['/hub/freelance?utm_source=newsletter&da=altro&utm_campaign=orbita'])
  })

  it('says the page even when there is no campaign, and remembers no campaign', () => {
    const landing = load()
    const root = fixture(['/hub/freelance', '/hub/aziende'])
    expect(landing.carryUtm(root, '?ref=friend', '/pigrocrm')).toBe(2)
    expect(hrefsOf(root)).toEqual(['/hub/freelance?da=pigrocrm', '/hub/aziende?da=pigrocrm'])
    expect(window.sessionStorage.getItem('orbiters.utm')).toBeNull()
    expect(window.sessionStorage.getItem('orbiters.da')).toBe('pigrocrm')
  })

  it('names the page by its path, home for the front door', () => {
    const landing = load()
    expect(landing.pageSlug('/')).toBe('home')
    expect(landing.pageSlug('/pigrocrm')).toBe('pigrocrm')
    expect(landing.pageSlug('/pigrocrm/')).toBe('pigrocrm')
    expect(landing.pageSlug('/Strana Pagina!')).toBe('strana-pagina-')
  })

  it('caps a value at 200 characters, like the hub does', () => {
    const landing = load()
    const long = 'x'.repeat(250)
    expect(landing.readUtm(`?utm_content=${long}`).get('utm_content')).toHaveLength(200)
  })
})
