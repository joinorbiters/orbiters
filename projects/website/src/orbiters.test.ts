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
    // The length rule is visible in the field rather than discovered in a 422. The
    // numbers are the API's columns: 120/120/320/300.
    expect(inputs.map((tag) => tag.match(/maxlength="(\d+)"/)?.[1])).toEqual([
      '120',
      '120',
      '320',
      '300',
    ])
    // The error text lives in #note; without this a screen reader hears "invalid" on
    // the focused field and never the reason.
    expect(inputs.every((tag) => tag.includes('aria-describedby="note"'))).toBe(true)
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

  it('writes no third-party tag into its markup, and stores nothing in the browser', () => {
    // Until 2026-09-09 this said "measures nothing", and it was true. The page now
    // carries the ChatGPT Ads pixel, because this is where the conversion happens --
    // so what is left of the old rule is the part still worth enforcing: no tag
    // written into the markup, no second analytics stack, and no state kept on the
    // visitor's machine by our own script. Which pages may carry the pixel, and what
    // it is allowed to do, is `pixel.test.ts`.
    expect(html).not.toMatch(/(?:href|src)="https?:/)
    expect(html).not.toMatch(/gtag|googletagmanager|plausible|fathom|hotjar/i)
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
    // Commented source, so most of these bytes never ship. The ceiling moved from 7 KB
    // to 9 KB on 2026-09-09, when the file gained the conversion event: the oppref, the
    // event id shared with the server, and the guarded `measure`. Raised by one step
    // and not removed -- and the comments were cut back first, which is why it is 9 and
    // not 12. What actually protects the visitor is the *shipped* budget, asserted per
    // page in `e2e/site.spec.ts` (40 KB); this one keeps the source from quietly
    // becoming an application.
    expect(Buffer.byteLength(js, 'utf-8')).toBeLessThan(9 * 1024)
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

  describe('the oppref of an ad click', () => {
    function load(): (search: string) => string | null {
      new Function(js)()
      return (window as unknown as { __orbiters: { opprefFrom: (s: string) => string | null } })
        .__orbiters.opprefFrom
    }

    it('is passed on unchanged, only bounded in length', () => {
      // OpenAI's instruction is "pass unchanged": its shape is theirs to decide, and a
      // value we did not recognise is still the value that arrived. So no parsing, no
      // normalising -- a ceiling, and nothing else.
      const opprefFrom = load()
      expect(opprefFrom('?oppref=abc.DEF-123_%7Bx%7D')).toBe('abc.DEF-123_{x}')
      expect(opprefFrom('?oppref=' + 'a'.repeat(600))).toBe('a'.repeat(512))
    })

    it('is nothing when the URL has none, or only spaces', () => {
      expect(load()('')).toBeNull()
      expect(load()('?utm_source=linkedin')).toBeNull()
      expect(load()('?oppref=%20%20')).toBeNull()
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

  type Answer = { ok: boolean; status: number; json?: () => Promise<unknown> }

  function mount(search = '', answer: Answer = { ok: true, status: 201 }): void {
    document.body.innerHTML = formHtml + noteHtml
    bodies = []
    window.history.replaceState({}, '', '/orbiters' + search)
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init: { body: string }) => {
        bodies.push(JSON.parse(init.body) as Record<string, unknown>)
        return Promise.resolve(answer)
      }),
    )
    new Function(js)()
  }

  /** What the API actually answers on a refused field -- see the API test
   *  `test_the_422_names_the_field_it_refused_so_the_form_can_point_at_it`. */
  function refusedField(name: string): Answer {
    return {
      ok: false,
      status: 422,
      json: () => Promise.resolve({ detail: [{ loc: ['body', name], msg: 'no' }] }),
    }
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
    const [body] = bodies
    expect(typeof body.pixel_event_id).toBe('string')
    expect(body).toEqual({
      email: 'ada@studio.it',
      nome: 'Ada',
      cognome: 'Lovelace',
      // Always present, even with the pixel blocked: the server event is sent either
      // way, and this is what makes it the same conversion as the browser one.
      pixel_event_id: body.pixel_event_id,
    })
    // No `oppref` key when the URL carried none, for the reason `utm` has none: an
    // absent value is absent, not an empty string in a column.
    expect(body).not.toHaveProperty('oppref')
    expect(note().textContent).toBe('Sei in orbita. Ti scriviamo noi.')
    expect((document.getElementById('signup') as HTMLFormElement).hidden).toBe(true)
  })

  it('sends the LinkedIn profile when there is one, alongside the attribution', async () => {
    mount('?utm_source=linkedin&oppref=clic-123')
    fill({ ...filled, linkedin_url: 'https://www.linkedin.com/in/ada' })
    await submit()
    const [body] = bodies
    expect(body).toEqual({
      email: 'ada@studio.it',
      nome: 'Ada',
      cognome: 'Lovelace',
      linkedin_url: 'https://www.linkedin.com/in/ada',
      utm: { utm_source: 'linkedin' },
      // The click identifier travels to the API because the *server* event needs it:
      // a request from our backend carries no cookie the ad platform set.
      oppref: 'clic-123',
      pixel_event_id: body.pixel_event_id,
    })
  })

  it('measures the conversion once, with the id it sent to the API', async () => {
    const calls: unknown[][] = []
    vi.stubGlobal(
      'oaiq',
      vi.fn((...args: unknown[]) => {
        calls.push(args)
      }),
    )
    mount()
    fill(filled)
    await submit()
    expect(calls).toEqual([
      [
        'measure',
        'registration_completed',
        { type: 'customer_action' },
        { event_id: bodies[0].pixel_event_id },
      ],
    ])
  })

  it('measures nothing when the API refused the signup', async () => {
    const calls: unknown[][] = []
    vi.stubGlobal(
      'oaiq',
      vi.fn((...args: unknown[]) => {
        calls.push(args)
      }),
    )
    mount('', refusedField('email'))
    fill(filled)
    await submit()
    expect(calls).toEqual([])
  })

  it('still says the signup worked when the pixel is blocked or throws', async () => {
    // An ad blocker replaces or removes the SDK. Whoever signed up is in orbit anyway,
    // and must be told so.
    vi.stubGlobal(
      'oaiq',
      vi.fn(() => {
        throw new Error('bloccato da un estensione')
      }),
    )
    mount()
    fill(filled)
    await submit()
    expect(note().textContent).toBe('Sei in orbita. Ti scriviamo noi.')
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
    expect(document.activeElement).toBe(field(name))
  })

  it.each([
    'linkedin.com/in/ada',
    'https://example.com/in/ada',
    'http://www.linkedin.com/in/ada',
    // These three are the reason the check parses the URL instead of searching it: the
    // host is a substring of the path or of a longer domain, not the host.
    'https://notlinkedin.com/in/ada',
    'https://evil.com/linkedin.com/ada',
    'https://example.com/?u=linkedin.com/ada',
    'https://linkedin.com.evil.com/in/ada',
    'non e un indirizzo',
  ])('refuses %s: a profile is https and on linkedin.com', async (value) => {
    mount()
    fill({ ...filled, linkedin_url: value })
    await submit()
    expect(bodies).toEqual([])
    expect(note().textContent).toBe('Controlla il profilo LinkedIn e riprova.')
    expect(field('linkedin_url').getAttribute('aria-invalid')).toBe('true')
    expect(document.activeElement).toBe(field('linkedin_url'))
  })

  it.each([
    'https://www.linkedin.com/in/ada',
    'https://linkedin.com/in/ada',
    'https://it.linkedin.com/in/ada',
  ])('accepts %s', async (value) => {
    mount()
    fill({ ...filled, linkedin_url: value })
    await submit()
    expect(bodies[0]?.linkedin_url).toBe(value)
  })

  it.each([
    ['nome', 'Scrivi il tuo nome e riprova.'],
    ['cognome', 'Scrivi il tuo cognome e riprova.'],
    ['email', "Controlla l'indirizzo e riprova."],
    ['linkedin_url', 'Controlla il profilo LinkedIn e riprova.'],
  ])('blames %s when the API is the one refusing it', async (name, message) => {
    mount('', refusedField(name))
    fill(filled)
    await submit()
    expect(note().textContent).toBe(message)
    expect(field(name).getAttribute('aria-invalid')).toBe('true')
    expect(document.activeElement).toBe(field(name))
  })

  it('falls back to the address when a 422 says nothing it can use', async () => {
    mount('', { ok: false, status: 422, json: () => Promise.reject(new Error('vuoto')) })
    fill(filled)
    await submit()
    expect(note().textContent).toBe("Controlla l'indirizzo e riprova.")
    expect(field('email').getAttribute('aria-invalid')).toBe('true')
  })

  it('still refuses an address that is not one', async () => {
    mount()
    fill({ ...filled, email: 'ciao' })
    await submit()
    expect(bodies).toEqual([])
    expect(note().textContent).toBe("Controlla l'indirizzo e riprova.")
    expect(field('email').getAttribute('aria-invalid')).toBe('true')
  })
})
