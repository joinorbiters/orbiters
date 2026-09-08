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
    // The trap named in spec 9.2: Acme's index.html still carries "Humancraft is
    // the AI optimization platform for human and AI agents" from the scaffold it
    // was generated out of (.reference-acme/website/index.html:7-10), describing
    // a product that exists nowhere in that codebase. It is the easiest mistake
    // to repeat, and it is text Google reads during verification.
    expect(description).not.toMatch(/AI optimization platform/i)
    expect(meta(page, 'og:title')).toBeTruthy()
    expect(meta(page, 'og:description')).toBeTruthy()
    expect(meta(page, 'og:type')).toBe('website')
  })

  it('requests nothing from another origin', () => {
    for (const [, url] of page.matchAll(/(?:href|src)="(https?:\/\/[^"]+)"/g)) {
      // An href the reader clicks -- the repository, or the hosted signup -- is fine;
      // a subresource is not.
      expect(url, 'external subresource').toMatch(
        /^https:\/\/(?:github\.com|pigro\.joinorbiters\.com|humancraft\.tech)\//,
      )
    }
    expect(page).not.toMatch(/fonts\.googleapis\.com|fonts\.gstatic\.com/)
    expect(page).not.toMatch(/<link[^>]+href="https?:/)
    expect(page).not.toMatch(/<script[^>]+src="https?:/)
  })

  it('offers a way into an existing installation', () => {
    // Spec 9.1 purpose 4: whoever opens the root of their own instance must not
    // be stranded on advertising copy.
    expect(page).toMatch(/href="\/app\/"/)
    expect(page).toContain('Accedi')
  })

  it('signs itself with the four-tile glyph before the name', () => {
    expect(page).toMatch(/<a class="brand" href="\/"><span class="glyph" aria-hidden="true"><\/span>PigroCRM<\/a>/)
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
    const claim = page.indexOf('La prima community per freelancer costruita da freelancer.')
    const perk = page.indexOf('PigroCRM, il perk')
    expect(claim).toBeGreaterThan(0)
    expect(perk).toBeGreaterThan(claim)
    expect(page).toContain('Gratis per chi è in community.')
  })

  it('sends the visitor into the community first, and to their space second', () => {
    expect(page).toMatch(/<a class="cta" href="\/orbiters">Entra in Orbiters<\/a>/)
    expect(page).toContain('href="https://pigro.joinorbiters.com/app/registrati"')
    // No invented plan or trial: the one price is "be in the community".
    expect(page).not.toMatch(/Prova gratis|abbonamento|piano (Pro|Business)/i)
  })

  it('says who it is for, in the words that qualify a reader in fifteen seconds', () => {
    for (const word of ['freelance', 'forfettario', 'self-hosted', 'gratis']) {
      expect(page.toLowerCase()).toContain(word)
    }
  })

  it('links the two pages Google reads during verification', () => {
    expect(page).toMatch(/href="\/privacy"/)
    expect(page).toMatch(/href="\/termini"/)
  })

  it('mounts the field behind the hero, from the shared script', () => {
    expect(page).toMatch(/<canvas id="hero-field" aria-hidden="true">/)
    expect(page).toMatch(/<script type="module" src="\.\/field\.js"><\/script>\s*<script type="module" src="\.\/landing\.js">/)
  })

  it('collects nothing and measures nothing', () => {
    expect(page).not.toMatch(/<form/i)
    expect(page).not.toMatch(/<input/i)
    expect(page).not.toMatch(/gtag|googletagmanager|analytics|plausible|fathom|hotjar|pixel/i)
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
