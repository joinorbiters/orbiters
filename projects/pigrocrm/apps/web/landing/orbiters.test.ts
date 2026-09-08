import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const html = readFileSync(join(__dirname, 'orbiters.html'), 'utf-8')
const css = readFileSync(join(__dirname, 'orbiters.css'), 'utf-8')
const js = readFileSync(join(__dirname, 'orbiters.js'), 'utf-8')

function meta(name: string): string | undefined {
  return html.match(new RegExp(`<meta\\s+(?:name|property)="${name}"\\s+content="([^"]*)"`))?.[1]
}

describe('orbiters.html', () => {
  it('is in Italian, names itself, and describes itself', () => {
    expect(html).toMatch(/<html lang="it">/)
    expect(html.match(/<title>([^<]+)<\/title>/)?.[1]).toContain('Orbiters')
    expect((meta('description') ?? '').length).toBeGreaterThan(40)
    expect(meta('og:type')).toBe('website')
    expect(meta('og:title')).toContain('Orbiters')
  })

  it('has exactly one form, and it asks for one thing', () => {
    expect(html.match(/<form/g)).toHaveLength(1)
    expect(html.match(/<input/g)).toHaveLength(1)
    expect(html).toMatch(/<input[^>]+type="email"/)
    expect(html).toMatch(/<label[^>]+for="email"/)
    expect(html).toMatch(/<button type="submit">Entra in orbita<\/button>/)
  })

  it('does not post the form anywhere without the script', () => {
    // The endpoint speaks JSON. A native `action=` would send it urlencoded and show
    // the visitor a 422 they cannot read; the noscript line is the honest version.
    expect(html).not.toMatch(/<form[^>]+action=/)
    expect(html).toContain('<noscript>')
  })

  it('speaks to the reader, in the second person and in a few words', () => {
    const text = html
      .replace(/<head>[\s\S]*<\/head>/, '')
      .replace(/<[^>]+>/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
    expect(text.split(' ').length).toBeLessThan(90)
    expect(text).toContain('Lascia l\'email')
    for (const word of ['freelance', 'fatturare']) {
      expect(text.toLowerCase()).toContain(word)
    }
  })

  it('requests nothing from another origin and measures nothing', () => {
    expect(html).not.toMatch(/(?:href|src)="https?:/)
    expect(html).not.toMatch(/gtag|googletagmanager|analytics|plausible|fathom|hotjar|pixel/i)
    expect(js).not.toMatch(/https?:\/\//)
    expect(js).not.toMatch(/localStorage|sessionStorage|document\.cookie|navigator\.sendBeacon/)
  })

  it('says where the email goes and how to get out', () => {
    expect(html).toMatch(/href="\/privacy"/)
    const privacy = readFileSync(join(__dirname, 'privacy.html'), 'utf-8')
    expect(privacy).toContain('Orbiters')
    expect(privacy).toMatch(/href="\/orbiters"/)
  })

  it('still offers the way into an installation, quietly', () => {
    expect(html).toMatch(/href="\/app\/"/)
  })
})

describe('orbiters.css', () => {
  it('restates no colour: every hex but white is a token', () => {
    const hexes = [...css.matchAll(/#[0-9a-fA-F]{3,8}\b/g)].map((m) => m[0].toLowerCase())
    expect(new Set(hexes)).toEqual(new Set(['#ffffff']))
    expect(css).toMatch(/var\(--color-prussian-blue\)/)
  })

  it('has hard edges: no radius, no blur, no soft shadow', () => {
    expect(css).not.toMatch(/border-radius:(?!\s*0;)/)
    expect(css).not.toMatch(/backdrop-filter|blur\(/)
    for (const [, shadow] of css.matchAll(/box-shadow:\s*([^;]+);/g)) {
      // Offsets only: `x y 0 colour`, never a blur radius.
      for (const layer of (shadow ?? '').split(',')) {
        expect(layer.trim()).toMatch(/^-?\d+(?:px)? -?\d+(?:px)? 0 /)
      }
    }
  })

  it('actually hides the form once it is hidden', () => {
    // The author `display: grid` on .signup outranks the UA `[hidden]` rule.
    expect(css).toMatch(/\.signup\[hidden\]\s*\{\s*display:\s*none;/)
  })

  it('does not import the landing sheet', () => {
    expect(css).not.toMatch(/@import/)
  })
})

describe('orbiters.js', () => {
  it('stays small', () => {
    // Commented source; Vite ships it at about 2.6 KB. The whole page, font aside,
    // sits under 10 KB against the landing's 40 KB budget (e2e/landing.spec.ts).
    expect(Buffer.byteLength(js, 'utf-8')).toBeLessThan(7 * 1024)
  })

  it('carries no colour of its own', () => {
    expect(js).not.toMatch(/#[0-9a-fA-F]{6}\b/)
  })

  it('posts to the one endpoint, as JSON', () => {
    expect(js).toContain("fetch('/api/orbiters/signups'")
    expect(js).toMatch(/'Content-Type':\s*'application\/json'/)
  })

  it('asks the field to drift; the field decides about reduced motion', () => {
    expect(js).toMatch(/animate:\s*true/)
  })

  describe('the attribution', () => {
    function load() {
      new Function(js)()
      const api = (window as unknown as { __orbiters?: { utmFrom: (s: string) => unknown } })
        .__orbiters
      if (!api) throw new Error('orbiters.js did not expose window.__orbiters')
      return api.utmFrom
    }

    it('reads only the six utm_ keys, trimmed and bounded', () => {
      const utmFrom = load()
      expect(
        utmFrom('?utm_id=%7B%7BAD_SET_ID%7D%7D&utm_source=linkedin&utm_medium=paid-social&gclid=x&foo=1'),
      ).toEqual({ utm_source: 'linkedin', utm_medium: 'paid-social', utm_id: '{{AD_SET_ID}}' })
      expect(utmFrom('?utm_source=' + 'a'.repeat(300))).toEqual({ utm_source: 'a'.repeat(200) })
      expect(utmFrom('?utm_source=%20%20&utm_medium=')).toBeNull()
    })

    it('is nothing when the URL says nothing, so the body stays the bare email', () => {
      expect(load()('')).toBeNull()
      expect(load()('?ref=abc')).toBeNull()
      expect(js).toMatch(/utm \? \{ email: email, utm: utm \} : \{ email: email \}/)
    })
  })

  it('paints its field through the shared field.js, loaded first', () => {
    expect(js).toMatch(/window\.__pigroField/)
    expect(js).not.toMatch(/function noise|fillRect/)
    expect(html).toMatch(
      /<script type="module" src="\.\/field\.js"><\/script>\s*<script type="module" src="\.\/orbiters\.js">/,
    )
  })
})
