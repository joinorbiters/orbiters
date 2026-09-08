import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

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

  it('has one form, and it asks for four things, three of them required', () => {
    expect(html.match(/<form/g)).toHaveLength(1)
    const inputs = [...html.matchAll(/<input[\s\S]*?\/>/g)].map((match) => match[0])
    expect(inputs.map((tag) => tag.match(/name="([^"]+)"/)?.[1])).toEqual([
      'nome',
      'cognome',
      'email',
      'linkedin_url',
    ])
    // The LinkedIn profile is the one thing nobody has to give.
    expect(inputs.filter((tag) => /\brequired\b/.test(tag))).toHaveLength(3)
    expect(html).toMatch(/<input[^>]+type="email"/)
    expect(html).toMatch(/<input[^>]+type="url"/)
    for (const name of ['nome', 'cognome', 'email', 'linkedin_url']) {
      expect(html).toMatch(new RegExp(`<label[^>]+for="${name}"`))
    }
    expect(html).toContain('Profilo LinkedIn (facoltativo)')
    expect(html).toContain('placeholder="https://www.linkedin.com/in/\u2026"')
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
    // The one absolute URL the script contains is the scheme a LinkedIn profile has to
    // start with -- a string it compares against, never something it fetches. The only
    // fetch is the relative endpoint asserted below.
    expect(js.match(/https?:\/\/[^\s'"]*/g)).toEqual(['https://'])
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

    it('is nothing when the URL says nothing, so the body carries no utm key', () => {
      expect(load()('')).toBeNull()
      expect(load()('?ref=abc')).toBeNull()
      expect(js).toMatch(/if \(utm\) payload\.utm = utm/)
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

describe('the form, once the script has hold of it', () => {
  const formHtml = html.match(/<form[\s\S]*?<\/form>/)?.[0] ?? ''
  const noteHtml = html.match(/<p class="note" id="note"[\s\S]*?<\/p>/)?.[0] ?? ''
  const filled = { nome: '  Ada  ', cognome: 'Lovelace', email: 'ada@studio.it', linkedin_url: '' }
  let bodies: Array<Record<string, unknown>> = []

  function mount(search = ''): void {
    document.body.innerHTML = formHtml + noteHtml
    bodies = []
    window.history.replaceState({}, '', '/orbiters' + search)
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init: { body: string }) => {
        bodies.push(JSON.parse(init.body) as Record<string, unknown>)
        return Promise.resolve({ ok: true, status: 201 })
      }),
    )
    new Function(js)()
  }

  function field(name: string): HTMLInputElement {
    return document.querySelector(`input[name="${name}"]`) as HTMLInputElement
  }

  function fill(values: Record<string, string>): void {
    for (const [name, value] of Object.entries(values)) field(name).value = value
  }

  function note(): HTMLElement {
    return document.getElementById('note') as HTMLElement
  }

  async function submit(): Promise<void> {
    const form = document.getElementById('signup') as HTMLFormElement
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await new Promise((resolve) => setTimeout(resolve, 0))
  }

  afterEach(() => {
    vi.unstubAllGlobals()
    document.body.innerHTML = ''
  })

  it('sends the four fields trimmed, and no LinkedIn key when nobody gave one', async () => {
    mount()
    fill(filled)
    await submit()
    expect(bodies).toEqual([{ email: 'ada@studio.it', nome: 'Ada', cognome: 'Lovelace' }])
    expect(note().textContent).toBe('Sei in orbita. Ti scriviamo noi.')
    expect((document.getElementById('signup') as HTMLFormElement).hidden).toBe(true)
  })

  it('sends the LinkedIn profile when there is one, alongside the attribution', async () => {
    mount('?utm_source=linkedin')
    fill({ ...filled, linkedin_url: 'https://www.linkedin.com/in/ada' })
    await submit()
    expect(bodies).toEqual([
      {
        email: 'ada@studio.it',
        nome: 'Ada',
        cognome: 'Lovelace',
        linkedin_url: 'https://www.linkedin.com/in/ada',
        utm: { utm_source: 'linkedin' },
      },
    ])
  })

  it.each([
    ['nome', 'Scrivi il tuo nome e riprova.'],
    ['cognome', 'Scrivi il tuo cognome e riprova.'],
  ])('asks for the %s before it posts anything', async (name, message) => {
    mount()
    fill({ ...filled, [name]: '   ' })
    await submit()
    expect(bodies).toEqual([])
    expect(note().textContent).toBe(message)
    expect(note().getAttribute('data-tone')).toBe('error')
    expect(field(name).getAttribute('aria-invalid')).toBe('true')
  })

  it.each(['linkedin.com/in/ada', 'https://example.com/in/ada', 'http://www.linkedin.com/in/ada'])(
    'refuses %s: a profile is https and on linkedin.com',
    async (value) => {
      mount()
      fill({ ...filled, linkedin_url: value })
      await submit()
      expect(bodies).toEqual([])
      expect(note().textContent).toBe('Controlla il profilo LinkedIn e riprova.')
      expect(field('linkedin_url').getAttribute('aria-invalid')).toBe('true')
    },
  )

  it('still refuses an address that is not one', async () => {
    mount()
    fill({ ...filled, email: 'ciao' })
    await submit()
    expect(bodies).toEqual([])
    expect(note().textContent).toBe("Controlla l'indirizzo e riprova.")
    expect(field('email').getAttribute('aria-invalid')).toBe('true')
  })
})
