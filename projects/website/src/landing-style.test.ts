import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { BRAND_TILES, BRAND_TILE_VARS } from '@orbiters/brand/mark'

const css = readFileSync(join(__dirname, 'landing.css'), 'utf-8')
const orbiters = readFileSync(join(__dirname, 'orbiters.css'), 'utf-8')
const system = readFileSync(join(__dirname, 'system.css'), 'utf-8')
const appTokens = readFileSync(fileURLToPath(import.meta.resolve('@orbiters/brand/palette.css')), 'utf-8')

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

  it('draws the grid on these two surfaces only: the app stopped', () => {
    // This assertion used to read the other way round -- the app restated the same
    // line and tile, because Tailwind cannot import system.css. The app UI revision
    // (2026-09-08, docs/superpowers/specs/2026-09-08-ui-revision-design.md §3) removed
    // the grid from the app body: its white content panel covers the page, and the
    // grid was the one thing tying the app's shapes to Orbiters'. The landing and
    // Orbiters are unchanged and keep it, so system.css is now its single declaration
    // and there is nothing left in the app to drift from it.
    expect(appTokens).not.toMatch(/--grid-line/)
    expect(appTokens).not.toMatch(/background-image:/)
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

  it('signs itself with the four tiles of the brand mark, in reading order', () => {
    expect(css).not.toMatch(/\.glyph/)
    expect(orbiters).not.toMatch(/\.glyph/)
    const glyph = rule('.glyph', system)
    // One element and three shadows: the tile itself is the first of the four.
    const drawn = [
      glyph.match(/background-color:\s*([^;]+);/)?.[1]?.trim(),
      glyph.match(/6px 0 0 ([^,\n]+)/)?.[1]?.trim(),
      glyph.match(/0 6px 0 ([^,\n]+)/)?.[1]?.trim(),
      glyph.match(/6px 6px 0 ([^,;\n]+)/)?.[1]?.trim(),
    ]
    // Against `shared/brand`, not against the application's component: the mark is
    // the brand's, and three surfaces draw it in three technologies. The application
    // asserts the same order on its own side, in BrandMark.test.tsx.
    expect(drawn).toEqual(BRAND_TILES.map((tile) => BRAND_TILE_VARS[tile]))
  })

  it('has no entrance animation and nothing tied to scroll', () => {
    // The initial state is the final state. Nothing to reveal means nothing that a
    // failed script can leave hidden, and nothing that accumulates on a long page.
    // The one animation both pages carry, the title's cursor, is in system.css and
    // is checked below: it decorates a word that is already there.
    expect(css).not.toMatch(/\.rise|data-hidden|@keyframes|animation:|transition:/)
    expect(css).not.toMatch(/animation-timeline|scroll\(\)|view\(\)/)
  })

  describe('the title\'s cursor (ORB-24)', () => {
    it('is a bar of the ink, blinking in steps, only while the script types', () => {
      const cursor = rule('h1 .role.is-typing::after', system)
      expect(cursor).toMatch(/content:\s*''/)
      expect(cursor).toMatch(/background-color:\s*currentColor/)
      expect(cursor).toMatch(/animation:\s*blink 1s step-end infinite/)
      expect(system).toMatch(/@keyframes blink\s*\{[^}]*50%\s*\{\s*opacity:\s*0;?\s*\}/)
      // No hex, no other colour: the bar is the text's own.
      expect(cursor).not.toMatch(/#[0-9a-fA-F]{3,8}\b|var\(--color/)
    })

    it('is gone under reduced motion, whatever the script did', () => {
      expect(system).toMatch(
        /@media \(prefers-reduced-motion: reduce\)\s*\{\s*h1 \.role::after\s*\{\s*display:\s*none;/,
      )
    })

    it('leaves the sr-only text out of the layout, once, for both pages', () => {
      expect(rule('.sr-only', system)).toMatch(/position:\s*absolute/)
      expect(rule('.sr-only', system)).toMatch(/clip-path:\s*inset\(50%\)/)
      expect(orbiters).not.toMatch(/\n\.sr-only\s*\{/)
      expect(css).not.toMatch(/\n\.sr-only\s*\{/)
    })

    it('does not let the testimonial\'s role size reach the title', () => {
      // `.role` was the testimonial caption's class before it was the title's word;
      // the small size stays on the caption.
      expect(rule('.who .role')).toMatch(/font-size:\s*0\.875rem/)
      expect(css).not.toMatch(/\n\.role\s*\{/)
    })
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

  it('paints the same field as the community page: fixed, behind everything, inert', () => {
    // Ivan, 2026-09-09: `/pigrocrm` shares its background with `/`. The rule is the
    // twin of `#field` in orbiters.css, declaration for declaration.
    for (const sheet of [css, orbiters]) {
      expect(rule('#field', sheet)).toMatch(/position:\s*fixed/)
      expect(rule('#field', sheet)).toMatch(/inset:\s*0/)
      expect(rule('#field', sheet)).toMatch(/z-index:\s*-1/)
      expect(rule('#field', sheet)).toMatch(/pointer-events:\s*none/)
    }
    expect(css).not.toMatch(/hero-field|isolation/)
  })

  it('keeps the call to action square, saturated once, and ink on hover', () => {
    expect(rule('.cta')).toMatch(/background-color:\s*var\(--landing-cta\)/)
    expect(rule('.cta')).not.toMatch(/border-radius/)
    expect(rule('.cta:hover')).toMatch(/background-color:\s*var\(--landing-ink\)/)
  })
})
