import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/**
 * Pins the `.site` scope added by ORB-73 (`docs/design/DECISIONS.md`, 2026-09-10): the
 * chooser, the two wizards and the thanks page follow `joinorbiters.com`'s own visual
 * system rather than the application's, and the admin area must not drift with it.
 * These assertions check the rules the decision creates -- no radius, no blur shadow,
 * a solid ink line -- rather than restating every literal, the way
 * `projects/website/src/landing-tokens.test.ts` pins the site's own stylesheet.
 */
const tokensCss = readFileSync(join(__dirname, 'tokens.css'), 'utf-8')
const brandCss = readFileSync(
  fileURLToPath(import.meta.resolve('@orbiters/brand/palette.css')),
  'utf-8',
)
const css = `${brandCss}\n${tokensCss}`

/** The declarations of one rule of tokens.css, by exact selector. */
function block(selector: string): string {
  const escaped = selector.replace(/[.[\]*+?^${}()|\\]/g, '\\$&')
  const body = css.match(new RegExp(`(?:^|\\n)${escaped}\\s*\\{([\\s\\S]*?)\\n\\}`))?.[1]
  if (!body) throw new Error(`rule "${selector}" not found in tokens.css`)
  return body
}

const site = block('.site')

/** The value one token is assigned inside one rule, by exact selector. */
function declaration(selector: string, token: string): string {
  const value = block(selector).match(new RegExp(`${token}:\\s*([^;]+);`))?.[1]
  if (!value) throw new Error(`${token} is not declared in "${selector}"`)
  return value.trim()
}

function hexToRgb(hex: string): [number, number, number] {
  const value = hex.replace('#', '')
  return [parseInt(value.slice(0, 2), 16), parseInt(value.slice(2, 4), 16), parseInt(value.slice(4, 6), 16)]
}

function relativeLuminance([r, g, b]: [number, number, number]): number {
  const channel = (c: number) => {
    const srgb = c / 255
    return srgb <= 0.03928 ? srgb / 12.92 : Math.pow((srgb + 0.055) / 1.055, 2.4)
  }
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
}

/** WCAG 2.x contrast ratio between two colours, order-independent. */
function contrastRatio(hexA: string, hexB: string): number {
  const a = relativeLuminance(hexToRgb(hexA))
  const b = relativeLuminance(hexToRgb(hexB))
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

/** Resolves a `--landing-*` colour declared in `.site` to the sRGB hex a browser
 *  would compute, by following its `var(--color-…)` back into the shared palette both
 *  this file and `landing.css` import. A hand-mixed hex here would be a second
 *  palette; this is what keeps that mechanically impossible rather than discouraged. */
function siteColourHex(token: string): string {
  const value = declaration('.site', token)
  const match = value.match(/^var\((--color-[\w-]+)\)$/)
  if (!match) throw new Error(`${token} is not var(--color-…): ${value}`)
  const hex = css.match(new RegExp(`${match[1]}:\\s*(#[0-9a-fA-F]{6})`))?.[1]
  if (!hex) throw new Error(`${match[1]} is not defined in the shared palette`)
  return hex
}

describe('the .site scope (ORB-73)', () => {
  it('resolves every --landing-* colour to the same hex the site itself pins', () => {
    // The site's own test (landing-tokens.test.ts) asserts these five against the
    // same shared palette; a value that drifted from either side would fail here too.
    expect(siteColourHex('--landing-surface')).toBe('#f1f2f3')
    expect(siteColourHex('--landing-ink')).toBe('#011936')
    expect(siteColourHex('--landing-ink-quiet')).toBe('#465362')
    expect(siteColourHex('--landing-cta')).toBe('#e5133e')
    expect(siteColourHex('--landing-focus')).toBe('#ed254e')
  })

  it('carries the CTA at 4.5:1 for its own ink, the same pair the application already relies on', () => {
    expect(contrastRatio(declaration('.site', '--landing-cta-ink'), siteColourHex('--landing-cta'))).toBeGreaterThanOrEqual(4.5)
  })

  it('contains no raw hexadecimal in the .site block, other than white', () => {
    for (const hex of site.match(/#[0-9a-fA-F]{3,8}\b/g) ?? []) {
      expect(hex.toLowerCase(), `raw hex in .site: ${hex}`).toBe('#ffffff')
    }
  })

  it('zeroes --radius, which zeroes the whole derived scale for its own subtree', () => {
    // --radius-sm .. --radius-4xl all read calc(var(--radius) * n) from the shared
    // @theme inline block: zeroing --radius here is enough, and a future rung added to
    // that scale inherits the same zero without a second edit to .site.
    expect(declaration('.site', '--radius')).toMatch(/^0(px)?$/)
  })

  it('draws a solid ink border and input line, never a tint', () => {
    // The application's own --border/--input are color-mix() tints of the ink; the
    // site's is the ink itself, full strength, the way landing.css's universal
    // selector sets border-color: var(--landing-ink) with no mixing at all.
    for (const token of ['--border', '--input']) {
      expect(declaration('.site', token), token).toBe('var(--landing-ink)')
    }
  })

  const SHADOWS = ['xs', 'sm', 'md', 'lg']

  it('points every @theme inline --shadow-* at a bare var(), never a compound expression', () => {
    // Tailwind v4 decomposes a compound theme value (`0 1px 1px var(--x)`) at build
    // time, baking the "0 1px 1px" into every `shadow-xs` utility and leaving only
    // the innermost var() live -- confirmed by compiling this file and reading
    // `.shadow-xs` back out of the built CSS, where it read `--shadow-ink-weak` and
    // never `--shadow-xs`. A `.site` override of `--shadow-xs` itself would therefore
    // never reach a rendered element; this is the one property `.site` must repoint
    // instead, and this test is what stops a future edit from re-inlining it.
    for (const step of SHADOWS) {
      expect(declaration('@theme inline', `--shadow-${step}`), `--shadow-${step}`).toBe(
        `var(--shadow-app-${step})`,
      )
    }
  })

  /** Splits a `box-shadow` value on whitespace outside of any parentheses, so a
   *  `calc(a * b)` or `var(--x)` component is never cut at its own inner paren. */
  function shadowParts(value: string): string[] {
    const parts: string[] = []
    let depth = 0
    let current = ''
    for (const char of value) {
      if (char === '(') depth += 1
      if (char === ')') depth -= 1
      if (char === ' ' && depth === 0) {
        if (current) parts.push(current)
        current = ''
      } else {
        current += char
      }
    }
    if (current) parts.push(current)
    return parts
  }

  it('casts every shadow as an ink offset, never a blur or a tint', () => {
    for (const step of SHADOWS) {
      const value = declaration('.site', `--shadow-app-${step}`)
      // <offset-x> <offset-y> 0 var(--landing-ink): the third length is the blur
      // radius, held at exactly 0 (landing.css:31, "an offset, never a blur"), and the
      // colour is the opaque ink rather than one of the application's low-opacity
      // shadow-ink-* tints.
      const parts = shadowParts(value)
      expect(parts, `--shadow-app-${step}`).toHaveLength(4)
      expect(parts[0], `--shadow-app-${step} offset-x`).toMatch(/^(?:calc\(.*\)|var\(.*\)|[\d.]+px)$/)
      expect(parts[1], `--shadow-app-${step} offset-y`).toMatch(/^(?:calc\(.*\)|var\(.*\)|[\d.]+px)$/)
      expect(parts[2], `--shadow-app-${step} blur`).toBe('0')
      expect(parts[3], `--shadow-app-${step} colour`).toBe('var(--landing-ink)')
    }
  })

  it('draws the box step no smaller than the card step, and neither past 8px', () => {
    // landing.css's own two magnitudes: 6px for .card, 8px for .box, the smaller one
    // three quarters of the larger (landing.css:31, landing.css:158).
    expect(declaration('.site', '--landing-step')).toBe('8px')
    expect(declaration('.site', '--shadow-app-xs')).toBe(declaration('.site', '--shadow-app-sm'))
    expect(declaration('.site', '--shadow-app-md')).toBe(declaration('.site', '--shadow-app-lg'))
    expect(shadowParts(declaration('.site', '--shadow-app-md'))[0]).toBe('var(--landing-step)')
    expect(shadowParts(declaration('.site', '--shadow-app-xs'))[0]).toBe('calc(var(--landing-step) * 0.75)')
  })

  it('leaves the admin area on the application tokens', () => {
    // :root, not .site, is what the admin area inherits: its radius and shadow scale
    // must still be the CRM's copy this file opens with.
    expect(css).toMatch(/@theme\s*\{\s*--radius:\s*10px;\s*\}/)
    expect(block(':root')).toMatch(/--shadow-ink-strong:\s*color-mix\(in oklab, var\(--color-prussian-blue\) 12%, transparent\)/)
  })
})
