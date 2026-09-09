import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const PAGES = ['index.html', 'privacy.html', 'termini.html'] as const
const html = Object.fromEntries(
  PAGES.map((name) => [name, readFileSync(join(__dirname, name), 'utf-8')]),
) as Record<(typeof PAGES)[number], string>

function meta(page: string, name: string): string | undefined {
  return page.match(new RegExp(`<meta\\s+(?:name|property)="${name}"\\s+content="([^"]*)"`))?.[1]
}

describe.each(PAGES)('%s', (name) => {
  const page = html[name]

  it('is in Italian and says so', () => {
    expect(page).toMatch(/<html lang="it">/)
  })

  it('carries its own title, description and Open Graph', () => {
    const title = page.match(/<title>([^<]+)<\/title>/)?.[1] ?? ''
    expect(title).toContain('PigroCRM')
    const description = meta(page, 'description') ?? ''
    expect(description.length).toBeGreaterThan(40)
    // The trap named in spec 9.2: the previous system's index.html still carries "Humancraft is
    // the AI optimization platform for human and AI agents" from the scaffold it
    // was generated out of (the reference copy/website/index.html:7-10), describing
    // a product that exists nowhere in that codebase. It is the easiest mistake
    // to repeat, and it is text Google reads during verification.
    expect(description).not.toMatch(/AI optimization platform/i)
    expect(meta(page, 'og:title')).toBeTruthy()
    expect(meta(page, 'og:description')).toBeTruthy()
    expect(meta(page, 'og:type')).toBe('website')
  })

  it('requests nothing from another origin, bar the one script it declares', () => {
    for (const [, url] of page.matchAll(/(?:href|src)="(https?:\/\/[^"]+)"/g)) {
      // An href the reader clicks -- the repository, the hosted signup, or OpenAI's
      // own privacy policy, which the cookie section has to point at -- is fine; a
      // subresource is not.
      expect(url, 'external subresource').toMatch(
        /^https:\/\/(?:github\.com|pigro\.joinorbiters\.com|humancraft\.tech|openai\.com)\//,
      )
    }
    expect(page).not.toMatch(/fonts\.googleapis\.com|fonts\.gstatic\.com/)
    expect(page).not.toMatch(/<link[^>]+href="https?:/)
    // Still no third-party tag written into the markup. Since 2026-09-09 index.html
    // *does* fetch one script from another origin -- the ChatGPT Ads measurement SDK,
    // injected by the inline snippet in its head -- and that is the single exception,
    // owned by `pixel.test.ts`: which pages may carry it, which must not, and that no
    // second analytics stack arrives beside it. Leaving this assertion as an
    // unqualified "nothing from another origin" would have made it a sentence that
    // passes while being false, which is worse than no assertion.
    expect(page).not.toMatch(/<script[^>]+src="https?:/)
  })

  it('offers a way into an existing installation', () => {
    // Spec 9.1 purpose 4: whoever opens the root of their own instance must not
    // be stranded on advertising copy.
    expect(page).toMatch(/href="\/app\/"/)
    expect(page).toContain('Accedi')
  })

  it('signs itself with the four-tile glyph before the name', () => {
    // The landing is Orbiters' since 2026-09-09 and signs as Orbiters; the two policy
    // pages are the product's and keep its name.
    const brand = name === 'index.html' ? 'Orbiters' : 'PigroCRM'
    expect(page).toMatch(
      new RegExp(`<a class="brand" href="/"><span class="glyph" aria-hidden="true"></span>${brand}</a>`),
    )
  })

  it('has no entrance animation to fail', () => {
    expect(page).not.toMatch(/class="[^"]*\brise\b|reveal\.js|class="grain"/)
  })
})

describe('index.html', () => {
  const page = html['index.html']

  it('opens with the community and its claim, then presents the CRM as the perk', () => {
    // Since 2026-09-08 PigroCRM is what a member of Orbiters gets: the page says what
    // Orbiters is first, in its own words, and only then what the CRM does.
    const claim = page.indexOf('ma non da soli.')
    const perk = page.indexOf('PigroCRM, il perk')
    expect(claim).toBeGreaterThan(0)
    expect(perk).toBeGreaterThan(claim)
    // The lead names the reader in the words of docs/design/positioning.md (ORB-24).
    expect(page.replace(/\s+/g, ' ')).toContain(
      'La community di chi fa software in proprio: developer, AI engineer, CTO e fractional CTO.',
    )
    expect(page).toContain('Gratis per chi è in community.')
  })

  it('has two doors in the hero, one per side of the marketplace, both into the hub', () => {
    // The hub (projects/hub) is where somebody signs up since 2026-09-09: the freelancer
    // wizard and the company wizard. Same origin, different deployable; the paths are
    // relative so the page has one origin in every environment.
    expect(page).toMatch(/<a class="cta" href="\/hub\/freelance">Entra come developer o CTO<\/a>/)
    expect(page).toMatch(/<a class="cta secondary" href="\/hub\/aziende">[^<]+<\/a>/)
    // The old door, the email form on `/`, is not what this page sells any more.
    expect(page).not.toMatch(/<a class="cta" href="\/orbiters">/)
    // Whoever is already in still finds their space.
    expect(page).toContain('href="https://pigro.joinorbiters.com/app/registrati"')
    // No invented plan or trial: the one price is "be in the community".
    expect(page).not.toMatch(/Prova gratis|abbonamento|piano (Pro|Business)/i)
  })

  it('explains itself in three steps and says what is inside', () => {
    expect(page).toContain('Come funziona')
    expect(page.match(/<li class="card">\s*<span class="step-number"/g)).toHaveLength(3)
    expect(page).toContain('Cosa trovi dentro')
  })

  it('has one section for clients and testimonials, four tiles, all still placeholders', () => {
    // Ivan's shape: «Ivan Sala ha lavorato per XYZ» plus a quote, one section for both
    // sides. Until the real ones arrive every tile says so in the markup; when they do,
    // the attribute goes and this assertion is rewritten to count the real ones.
    expect(page).toContain('Hanno lavorato con noi')
    const tiles = page.match(/<figure class="card testimonial"[^>]*>/g) ?? []
    expect(tiles).toHaveLength(4)
    for (const tile of tiles) expect(tile).toContain('data-placeholder="true"')
    expect(page).toContain('<strong>Ivan Sala</strong> ha lavorato per <strong>XYZ</strong>')
    expect(page.match(/<blockquote>/g)).toHaveLength(4)
  })

  it('says who it is for, in the words that qualify a reader in fifteen seconds', () => {
    // The words are docs/design/positioning.md's (ORB-24): the roles by name, the
    // fiscal reality, the price.
    for (const word of ['developer', 'ai engineer', 'fractional', 'forfettario', 'self-hosted', 'gratis', 'tariffa']) {
      expect(page.toLowerCase()).toContain(word)
    }
    expect(page).toMatch(/\bCTO\b/)
  })

  it('keeps "freelance" as the fiscal category, never as the headline', () => {
    // It stays in the sentence about forfettario, where it is the legal status, and in
    // the hub's route, which is code. It is gone from what a share on LinkedIn shows and
    // from what a visitor reads first.
    const headlines = [
      page.match(/<title>([^<]+)<\/title>/)?.[1],
      meta(page, 'og:title'),
      meta(page, 'description'),
      meta(page, 'og:description'),
      page.match(/<h1[^>]*>([\s\S]*?)<\/h1>/)?.[1]?.replace(/<[^>]+>/g, ' '),
      ...[...page.matchAll(/<a class="cta[^"]*" href="[^"]+">([^<]+)<\/a>/g)].map((m) => m[1]),
    ]
    expect(headlines.length).toBeGreaterThanOrEqual(9)
    for (const headline of headlines) expect(headline?.toLowerCase()).not.toContain('freelance')
    expect(page.toLowerCase()).toContain('freelance in italia, spesso in forfettario')
  })

  it('says where the CV goes before asking for it', () => {
    // The wizard takes a CV; a landing that sends people there owes them one sentence
    // about what happens to it, and the link to the rest.
    expect(page).toMatch(/Il CV resta nel nostro database/)
    expect(page).toMatch(/cancelliamo quando ce lo chiedi/)
  })

  it('links the two pages Google reads during verification', () => {
    expect(page).toMatch(/href="\/privacy"/)
    expect(page).toMatch(/href="\/termini"/)
  })

  it('mounts the same field as the community page behind the whole page, from the shared script', () => {
    // Ivan, 2026-09-09: `/pigrocrm` has the same background as `/`. One fixed canvas
    // right after <body>, the same id, the same mount options in landing.js.
    expect(page).toMatch(/<body>\s*(?:<!--[\s\S]*?-->\s*)?<canvas id="field" aria-hidden="true"><\/canvas>/)
    expect(page).not.toContain('hero-field')
    expect(page).toMatch(/<script type="module" src="\.\/field\.js"><\/script>\s*<script type="module" src="\.\/landing\.js">/)
  })

  it('collects nothing, and measures only after the visitor has agreed to it', () => {
    // Nothing is typed on this page: the forms live in the hub. What arrived on
    // 2026-09-09 is the measurement pixel, because this is a page an ad lands on -- so
    // "measures nothing" stopped being true, and pretending otherwise here would have
    // meant a test asserting the absence of a string that is in the file. What the page
    // carries is the consent script, and only that can load the pixel;
    // `pixel.test.ts` and `consent.test.ts` hold the gate itself.
    expect(page).not.toMatch(/<form/i)
    expect(page).not.toMatch(/<input/i)
    expect(page).not.toMatch(/gtag|googletagmanager|plausible|fathom|hotjar/i)
    expect(page).not.toContain('oaiq')
    expect(page.match(/<script[^>]+consent\.js/g)).toHaveLength(1)
  })
})

describe('privacy.html', () => {
  const page = html['privacy.html']

  it('names both restricted Gmail scopes, in full', () => {
    // Spec 13, criterion 26. Not pedantry: Google's review of a restricted scope
    // checks that the privacy policy states what the application does with the
    // data. Without this text 5B-1 stays in Testing, where a consumer refresh
    // token expires every seven days.
    expect(page).toContain('https://www.googleapis.com/auth/gmail.readonly')
    expect(page).toContain('https://www.googleapis.com/auth/gmail.send')
  })

  it('says what is read, what is stored, and what is never touched', () => {
    for (const claim of [
      'indirizzi email già presenti',
      'non leggiamo',
      'non trasferiamo',
      'sul tuo server',
      'revocare',
    ]) {
      expect(page.toLowerCase()).toContain(claim.toLowerCase())
    }
  })

  it('names the scopes it deliberately does not ask for', () => {
    // The consent screen shows what is requested; the policy is where "and not
    // these" belongs. gmail.modify would let the product touch the mailbox, and
    // it never does: the state lives in the CRM.
    expect(page).toContain('gmail.modify')
    expect(page).toContain('https://mail.google.com/')
  })

  it('gives a date, so a reviewer can tell when it was last true', () => {
    expect(page).toMatch(/<time datetime="\d{4}-\d{2}-\d{2}">/)
  })
})

describe('termini.html', () => {
  const page = html['termini.html']

  it('is honest that there is no service being provided', () => {
    for (const claim of ['nessuna garanzia', 'software', 'licenza']) {
      expect(page.toLowerCase()).toContain(claim)
    }
    expect(page).not.toMatch(/abbonamento|canone|SLA/i)
  })
})
