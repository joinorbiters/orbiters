/* The ChatGPT Ads measurement pixel: where it is, where it must not be, and the one
 * string that must never appear in a page.
 *
 * Every rule about the pixel lives in this file rather than being spread over the page
 * tests, because they are rules about one decision -- we measure the ad conversion, and
 * we measure nothing else -- and a rule split across three files is a rule that gets
 * half-changed. The page tests keep saying what a page is; this says what it may load.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const PIXEL_ID = '9r6qrnPxBV8WDVGtpuaqxh'
const SDK_URL = 'https://bzrcdn.openai.com/sdk/oaiq.min.js'

const MEASURED = ['index.html', 'orbiters.html'] as const
const UNMEASURED = ['privacy.html', 'termini.html'] as const
const ALL = [...MEASURED, ...UNMEASURED]

const page = Object.fromEntries(
  ALL.map((name) => [name, readFileSync(join(__dirname, name), 'utf-8')]),
) as Record<string, string>
const js = readFileSync(join(__dirname, 'orbiters.js'), 'utf-8')

describe.each(MEASURED)('%s', (name) => {
  it('initialises the pixel exactly once, with our own id', () => {
    // "Add a single Pixel configuration script per page" is OpenAI's own instruction:
    // two inits on one page produce two of every event.
    expect(page[name].match(/oaiq\('init'/g)).toHaveLength(1)
    expect(page[name]).toContain(`pixelId: '${PIXEL_ID}'`)
  })

  it('loads the SDK from the documented URL and nowhere else', () => {
    expect(page[name]).toContain(SDK_URL)
    const external = [...page[name].matchAll(/https:\/\/[a-z0-9.-]+\.openai\.com[^'"\s]*/g)]
    expect(external.map((match) => match[0])).toEqual([SDK_URL])
  })

  it('puts the snippet in the head, before anything that could measure', () => {
    const head = page[name].slice(0, page[name].indexOf('</head>'))
    expect(head).toContain('oaiq')
  })
})

describe.each(UNMEASURED)('%s', (name) => {
  it('carries no pixel at all', () => {
    // A tracker on the privacy policy is the one place it cannot be defended, and
    // neither page is a landing an ad can point at.
    expect(page[name]).not.toContain('oaiq')
    expect(page[name]).not.toContain('bzrcdn')
    // A *link* to OpenAI's policy is not a pixel -- privacy.html has to point at it --
    // so what is refused is a script, not the name.
    expect(page[name]).not.toMatch(/<script[^>]*>[\s\S]*openai/i)
  })
})

describe.each(ALL)('%s', (name) => {
  it('contains no API key', () => {
    // The Conversions API key is a secret with full read and write access to the
    // conversion source. It belongs to the server's .env and to nothing that is
    // served to a browser -- and the cheapest way for it to end up in a page is
    // somebody pasting the whole setup snippet from the OpenAI console.
    expect(page[name]).not.toMatch(/sk-[A-Za-z0-9_-]{8}/)
    expect(page[name]).not.toMatch(/Authorization|Bearer/i)
  })

  it('measures through this pixel or not at all', () => {
    // No second analytics stack arriving next to the first. This is the assertion
    // that used to say "measures nothing" for index.html, and it is deliberately
    // still a closed list rather than a free hand.
    expect(page[name]).not.toMatch(/gtag|googletagmanager|plausible|fathom|hotjar|matomo|segment\.com/i)
  })
})

describe('privacy.html', () => {
  it('says the pixel exists, what it sends, and what it does not', () => {
    // The page used to read "nessun cookie di terze parti, nessuna analitica, nessun
    // pixel", which stopped being true the moment the snippet shipped. A privacy policy
    // that describes a site other than the one being served is worse than no policy, so
    // this test exists to make the two change together.
    const policy = page['privacy.html']
    expect(policy).toContain('ChatGPT Ads')
    expect(policy).toContain('__obref')
    // The three things we deliberately do not hand over. `emails_sha256` is off by
    // default in the API (`openai_conversions_send_hashed_email`), and if it is ever
    // switched on, this sentence becomes false and has to be rewritten first.
    expect(policy).toContain('Non gli mandiamo il tuo nome, la tua email né il tuo profilo')
    expect(policy).toMatch(/interesse legittimo/i)
    expect(policy).toContain('openai.com/policies/privacy-policy')
    // And the old absolute claim is gone rather than merely contradicted further down.
    expect(policy).not.toMatch(/Nessun cookie di terze parti, nessuna analitica, nessun\s+pixel/)
  })

  it('is dated the day it changed, so a reader can tell what it covers', () => {
    expect(page['privacy.html']).toContain('<time datetime="2026-09-09">')
  })
})

describe('the conversion event', () => {
  it('is registration_completed, as a customer action, after the API said yes', () => {
    expect(js).toContain("'measure', 'registration_completed', { type: 'customer_action' }")
    // The order is the whole point: the call sits after `say('Sei in orbita...')`,
    // which runs only on a response that was `ok`. A conversion measured on the click
    // would count a 422 and a dead network as signups.
    // `lastIndexOf`, because the first `measure(id)` in the file is the function's own
    // definition; the call site is the last one.
    expect(js.lastIndexOf('measure(id)')).toBeGreaterThan(js.indexOf('if (!response.ok) throw'))
  })

  it('carries an event_id, and the same one reaches the API', () => {
    // OpenAI deduplicates on (pixel id, event name, event_id): the browser event and
    // the server event are one conversion only if they carry the same id. One id per
    // submit, generated once, used twice.
    expect(js).toContain('payload.pixel_event_id = id')
    expect(js).toContain('event_id: id')
    expect(js.match(/var id = eventId\(\)/g)).toHaveLength(1)
  })

  it('never lets the pixel break the page', () => {
    // The SDK comes from another origin and is blocked by ordinary extensions. A
    // person who has just signed up must not see an error because of it.
    const measure = js.slice(js.indexOf('function measure(id)'), js.indexOf('/* The four fields'))
    expect(measure).toContain('try {')
    expect(measure).toContain('catch')
    expect(measure).toContain("typeof window.oaiq === 'function'")
  })
})
