import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(join(__dirname, 'landing.css'), 'utf-8')
const orbiters = readFileSync(join(__dirname, 'orbiters.css'), 'utf-8')
const system = readFileSync(join(__dirname, 'system.css'), 'utf-8')
const appTokens = readFileSync(join(__dirname, '../src/styles/tokens.css'), 'utf-8')
const brandMark = readFileSync(join(__dirname, '../src/components/BrandMark.tsx'), 'utf-8')

/** The declarations of one rule, by exact selector. */
function rule(selector: string, source = css): string {
  const escaped = selector.replace(/[.[\]*+?^${}()|\\]/g, '\\$&')
  const body = source.match(new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`))?.[1]
  if (!body) throw new Error(`rule "${selector}" not found`)
  return body
}

describe('the landing shares the product system', () => {
  it('sits on the grid system.css declares, as Orbiters does', () => {
    expect(rule('body')).toMatch(/linear-gradient\(to right, var\(--landing-grid\) 1px, transparent 1px\)/)
    expect(rule('body')).toMatch(/linear-gradient\(to bottom, var\(--landing-grid\) 1px, transparent 1px\)/)
    expect(rule('body')).toMatch(/background-size:\s*var\(--landing-cell\) var\(--landing-cell\)/)
    // Both sheets point at the shared line and tile rather than restating them.
    expect(css).toMatch(/--landing-grid:\s*var\(--system-grid\)/)
    expect(css).toMatch(/--landing-cell:\s*var\(--system-cell\)/)
    expect(orbiters).toMatch(/--orb-grid:\s*var\(--system-grid\)/)
    expect(orbiters).toMatch(/--orb-cell:\s*var\(--system-cell\)/)
    expect(system).toMatch(/--system-grid:\s*color-mix\(in oklab, var\(--color-prussian-blue\) 7%, transparent\)/)
    expect(system).toMatch(/--system-cell:\s*16px/)
    expect(css).not.toMatch(/color-mix\([^)]*7%/)
    expect(orbiters).not.toMatch(/color-mix\([^)]*7%/)
  })

  it('the app restates the same line and tile, because Tailwind cannot import system.css', () => {
    expect(appTokens).toMatch(/--grid-line:\s*color-mix\(in oklab, var\(--color-prussian-blue\) 7%, transparent\)/)
    expect(appTokens).toMatch(/background-size:\s*16px 16px/)
  })

  it('has hard edges: no radius, no blur, no soft shadow, no grain', () => {
    expect(css).not.toMatch(/border-radius:(?!\s*0;)/)
    expect(css).not.toMatch(/backdrop-filter|blur\(|radial-gradient|repeating-linear-gradient/)
    for (const [, shadow] of css.matchAll(/box-shadow:\s*([^;]+);/g)) {
      // Offsets only: `x y 0 colour`, never a blur radius.
      for (const layer of (shadow ?? '').split(',')) {
        expect(layer.trim()).toMatch(/^-?[\d.]+(?:px|rem)? -?[\d.]+(?:px|rem)? 0 |^var\(--landing-step\) var\(--landing-step\) 0 /)
      }
    }
  })

  it('draws its lines in the ink, two pixels wide, and never in a grey of its own', () => {
    expect(rule('*')).toMatch(/border-color:\s*var\(--landing-ink\)/)
    expect(rule('.box')).toMatch(/border-width:\s*2px/)
    expect(rule('.card')).toMatch(/border-width:\s*2px/)
    expect(rule('.rule')).toMatch(/border-top-width:\s*2px/)
    expect(css).not.toMatch(/hairline|--border\b/)
    expect(system).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })

  it('lifts the box off the grid by a whole step the colour of the ink', () => {
    expect(rule('.box')).toMatch(/box-shadow:\s*var\(--landing-step\) var\(--landing-step\) 0 var\(--landing-ink\)/)
    expect(rule('.card')).toMatch(/box-shadow:\s*6px 6px 0 var\(--landing-ink\)/)
  })

  it('signs itself with the four tiles system.css draws once, and BrandMark repeats', () => {
    expect(css).not.toMatch(/\.glyph/)
    expect(orbiters).not.toMatch(/\.glyph/)
    const glyph = rule('.glyph', system)
    expect(glyph).toMatch(/6px 0 0 var\(--color-royal-gold\)/)
    expect(glyph).toMatch(/0 6px 0 var\(--color-watermelon\)/)
    // The app's copy: ink, gold, watermelon, ink, in that reading order.
    const tiles = [...brandMark.matchAll(/<span className="([^"]+)" \/>/g)].map((m) => m[1])
    expect(tiles).toEqual([
      'bg-foreground',
      'bg-[var(--color-royal-gold)]',
      'bg-[var(--color-watermelon)]',
      'bg-foreground',
    ])
  })

  it('has no entrance animation and nothing tied to scroll', () => {
    // The initial state is the final state. Nothing to reveal means nothing that a
    // failed script can leave hidden, and nothing that accumulates on a long page.
    expect(css).not.toMatch(/\.rise|data-hidden|@keyframes|animation:|transition:/)
    expect(css).not.toMatch(/animation-timeline|scroll\(\)|view\(\)/)
  })

  it('uses sentence-case kickers, not tracked-out capitals', () => {
    expect(css).not.toMatch(/text-transform:\s*uppercase/)
    expect(css).not.toMatch(/letter-spacing:\s*0\.[2-9]/)
    expect(rule('.kicker::before')).toMatch(/background-color:\s*var\(--landing-cta\)/)
  })

  it('turns the field and the grid off when the reader asked for more contrast, once', () => {
    const block = system.match(/@media \(prefers-contrast: more\)\s*\{([\s\S]*?)\n\}/)?.[1] ?? ''
    expect(block).toMatch(/body\s*\{\s*background-image:\s*none/)
    expect(block).toMatch(/canvas\s*\{\s*display:\s*none/)
    expect(css).not.toMatch(/prefers-contrast/)
    expect(orbiters).not.toMatch(/prefers-contrast/)
  })

  it('keeps the kicker inline, so a sentence with a <time> in it still flows', () => {
    expect(rule('.kicker')).not.toMatch(/display:\s*flex/)
    expect(rule('.kicker::before')).toMatch(/display:\s*inline-block/)
  })

  it('gives the hero its own stacking context for the field behind it', () => {
    expect(rule('.hero')).toMatch(/isolation:\s*isolate/)
  })

  it('keeps the field inert and behind the text', () => {
    expect(rule('#hero-field')).toMatch(/z-index:\s*-1/)
    expect(rule('#hero-field')).toMatch(/pointer-events:\s*none/)
  })

  it('keeps the call to action square, saturated once, and ink on hover', () => {
    expect(rule('.cta')).toMatch(/background-color:\s*var\(--landing-cta\)/)
    expect(rule('.cta')).not.toMatch(/border-radius/)
    expect(rule('.cta:hover')).toMatch(/background-color:\s*var\(--landing-ink\)/)
  })
})
