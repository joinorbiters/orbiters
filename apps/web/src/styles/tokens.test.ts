import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(join(__dirname, 'tokens.css'), 'utf-8')

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
  const lighter = Math.max(a, b)
  const darker = Math.min(a, b)
  return (lighter + 0.05) / (darker + 0.05)
}

/** Reads whatever hex tokens.css currently assigns a colour token, so contrast
 *  gets recomputed from the live value on every run. A future edit to the hex
 *  is what this checks — a hand-written expected ratio would not notice. */
function tokenHex(name: string): string {
  const match = css.match(new RegExp(`--color-${name}:\\s*(#[0-9a-fA-F]{6})`))
  const hex = match?.[1]
  if (!hex) throw new Error(`token --color-${name} not found in tokens.css`)
  return hex
}

describe('design tokens', () => {
  it.each([
    ['watermelon', '#ed254e'],
    ['watermelon-strong', '#e5133e'],
    ['royal-gold', '#f9dc5c'],
    ['mint-cream', '#f4fffd'],
    ['prussian-blue', '#011936'],
    ['charcoal-blue', '#465362'],
  ])('defines %s as %s', (name, hex) => {
    expect(css).toContain(`--color-${name}: ${hex}`)
  })

  it('uses the accessible Watermelon variant as the primary and destructive colour', () => {
    // Raw --color-watermelon stays the brand colour for accents/borders/icons;
    // solid fills carrying white text need the darker, AA-compliant variant.
    expect(css).toMatch(/--primary:\s*var\(--color-watermelon-strong\)/)
    expect(css).toMatch(/--destructive:\s*var\(--color-watermelon-strong\)/)
  })

  it('white text on watermelon-strong clears the 4.5:1 AA text threshold', () => {
    const ratio = contrastRatio('#ffffff', tokenHex('watermelon-strong'))
    expect(ratio).toBeGreaterThanOrEqual(4.5)
  })

  it('defines a dark mode', () => {
    expect(css).toContain('.dark {')
  })

  it('does not load Reenie Beanie, which belongs to the landing page', () => {
    expect(css).not.toMatch(/Reenie/i)
  })
})
