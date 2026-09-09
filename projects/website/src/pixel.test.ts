/* The ChatGPT Ads measurement pixel: what may load it, where, and the one string that
 * must never appear in a page.
 *
 * Every rule about the pixel lives in this file rather than being spread over the page
 * tests, because they are rules about one decision -- we measure the ad conversion, we
 * measure nothing else, and we load nothing before somebody says yes -- and a rule
 * split across three files is a rule that gets half-changed. The page tests keep saying
 * what a page is; this says what it may fetch.
 *
 * The consent mechanics themselves are `consent.test.ts`, which drives the script in a
 * DOM. What is here is the static half: which pages can ever load the pixel, which must
 * not, and that no page contains a key.
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
const consent = readFileSync(join(__dirname, 'consent.js'), 'utf-8')
const orbiters = readFileSync(join(__dirname, 'orbiters.js'), 'utf-8')

describe.each(MEASURED)('%s', (name) => {
  it('loads the consent script, and that is the only way the pixel can arrive', () => {
    expect(page[name]).toMatch(/<script type="module" src="\.\/consent\.js"><\/script>/)
    // One script element, so one notice and one init. Counted as tags rather than as
    // occurrences of the name, which the comment above it also contains.
    expect(page[name].match(/<script[^>]+consent\.js/g)).toHaveLength(1)
  })

  it('contains no pixel of its own: no id, no SDK, no init', () => {
    // The gate is worth nothing if the snippet is also sitting in the markup. Before
    // 2026-09-09 it was, and consent was the change that took it out: markup runs
    // whatever the visitor decided.
    expect(page[name]).not.toContain(PIXEL_ID)
    expect(page[name]).not.toContain(SDK_URL)
    expect(page[name]).not.toContain('oaiq')
  })
})

describe.each(UNMEASURED)('%s', (name) => {
  it('carries no pixel and no notice, because it has nothing to ask about', () => {
    // A tracker on the privacy policy is the one place it cannot be defended, and
    // neither page is a landing an ad can point at -- so neither needs a notice either.
    expect(page[name]).not.toContain('consent.js')
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
    // conversion source. It belongs to the server's .env and to nothing that is served
    // to a browser -- and the cheapest way for it to end up in a page is somebody
    // pasting the whole setup snippet from the OpenAI console.
    expect(page[name]).not.toMatch(/sk-[A-Za-z0-9_-]{8}/)
    expect(page[name]).not.toMatch(/Authorization|Bearer/i)
  })

  it('measures through this pixel or not at all', () => {
    // No second analytics stack arriving next to the first. Deliberately a closed list
    // rather than a free hand.
    expect(page[name]).not.toMatch(
      /gtag|googletagmanager|plausible|fathom|hotjar|matomo|segment\.com/i,
    )
  })
})

describe('consent.js', () => {
  it('is the only file that names the pixel id or the SDK', () => {
    expect(consent).toContain(PIXEL_ID)
    expect(consent).toContain(SDK_URL)
    const external = [...consent.matchAll(/https:\/\/[a-z0-9.-]+\.openai\.com[^'"\s]*/g)]
    expect(external.map((match) => match[0])).toEqual([SDK_URL])
    // Not duplicated into the page script: one id, one place.
    expect(orbiters).not.toContain(PIXEL_ID)
  })

  it('injects the SDK from inside the accepting branch and nowhere else', () => {
    // The assertion that keeps the gate a gate. `loadPixel` is the only function that
    // touches the SDK URL, and the only call to it that is not behind a stored
    // `granted` is in `decide`, after the click.
    const load = consent.slice(
      consent.indexOf('function loadPixel'),
      consent.indexOf('function button'),
    )
    // The URL reaches a script element in exactly one place in the file, and that place
    // is inside `loadPixel`.
    expect(load).toContain('script.src = SDK_URL')
    expect(consent.match(/\.src = /g)).toHaveLength(1)
    expect(consent).toContain("if (decision === GRANTED) return loadPixel()")
    expect(consent).toContain("if (decision === GRANTED) loadPixel()")
  })

  it('asks again only while nothing has been decided', () => {
    // A refusal is remembered, so the notice does not come back on every page. That is
    // the difference between a notice and a nuisance.
    expect(consent).toContain('if (decision === DENIED) return')
    expect(consent).toContain('localStorage')
  })
})

describe('the conversion event', () => {
  it('is registration_completed, as a customer action, after the API said yes', () => {
    expect(orbiters).toContain("'measure', 'registration_completed', { type: 'customer_action' }")
    // The order is the whole point: the call sits after `say('Sei in orbita...')`,
    // which runs only on a response that was `ok`. A conversion measured on the click
    // would count a 422 and a dead network as signups. `lastIndexOf`, because the first
    // `measure(id)` in the file is the function's own definition.
    expect(orbiters.lastIndexOf('measure(id)')).toBeGreaterThan(
      orbiters.indexOf('if (!response.ok) throw'),
    )
  })

  it('carries an event_id, and the same one reaches the API', () => {
    // OpenAI deduplicates on (pixel id, event name, event_id): the browser event and
    // the server event are one conversion only if they carry the same id. One id per
    // submit, generated once, used twice.
    expect(orbiters).toContain('payload.pixel_event_id = id')
    expect(orbiters).toContain('event_id: id')
    expect(orbiters.match(/var id = eventId\(\)/g)).toHaveLength(1)
  })

  it('is a no-op under a refusal, because there is no oaiq to call', () => {
    // With consent denied `consent.js` never defines the stub, so this guard is what
    // makes a signup under a refusal measure nothing at all -- and it is also what
    // keeps a blocked SDK from breaking the page.
    const measure = orbiters.slice(
      orbiters.indexOf('function measure(id)'),
      orbiters.indexOf('/* The four fields'),
    )
    expect(measure).toContain("typeof window.oaiq === 'function'")
    expect(measure).toContain('try {')
    expect(measure).toContain('catch')
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
    expect(policy).toContain('openai.com/policies/privacy-policy')
    // And the old absolute claim is gone rather than merely contradicted further down.
    expect(policy).not.toMatch(/Nessun cookie di terze parti, nessuna analitica, nessun\s+pixel/)
  })

  it('says the pixel waits for a yes, and how to change your mind', () => {
    // Since the notice exists, the policy has to describe the actual mechanism rather
    // than an interest we assert: consent first, and a way back.
    const policy = page['privacy.html']
    expect(policy).toMatch(/consenso/i)
    expect(policy).toContain('<time datetime="2026-09-09">')
  })
})
