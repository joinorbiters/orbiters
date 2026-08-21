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
      // An href to a repository the reader clicks is fine; a subresource is not.
      expect(url, 'external subresource').toMatch(/^https:\/\/github\.com\//)
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

  it('lays the grain under the content', () => {
    expect(page).toMatch(/<body class="grain">/)
  })
})

describe('index.html', () => {
  const page = html['index.html']

  it('sends the visitor to the only action that exists', () => {
    // There is no public signup and the product stays single-tenant self-hosted.
    // A CTA promising a registration that does not exist is worse than no CTA.
    expect(page).toContain('Installala sul tuo server')
    expect(page).not.toMatch(/Prova gratis|Registrati|Iscriviti/i)
  })

  it('says who it is for, in the words that qualify a reader in fifteen seconds', () => {
    for (const word of ['freelance', 'forfettario', 'self-hosted']) {
      expect(page.toLowerCase()).toContain(word)
    }
  })

  it('links the two pages Google reads during verification', () => {
    expect(page).toMatch(/href="\/privacy"/)
    expect(page).toMatch(/href="\/termini"/)
  })

  it('collects nothing and measures nothing', () => {
    expect(page).not.toMatch(/<form/i)
    expect(page).not.toMatch(/<input/i)
    expect(page).not.toMatch(/gtag|googletagmanager|analytics|plausible|fathom|hotjar|pixel/i)
  })
})
