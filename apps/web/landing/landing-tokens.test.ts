import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { extractSharedTokens } from './palette-plugin'

const shared = extractSharedTokens(readFileSync(join(__dirname, '../src/styles/tokens.css'), 'utf-8'))
const landingCss = readFileSync(join(__dirname, 'landing.css'), 'utf-8')

type Triple = [number, number, number]

function toLinear(channel: number): number {
  const c = channel / 255
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
}

function toChannel(linear: number): number {
  const v = linear <= 0.0031308 ? linear * 12.92 : 1.055 * Math.pow(linear, 1 / 2.4) - 0.055
  return Math.min(255, Math.max(0, Math.round(v * 255)))
}

function hexToRgb(hex: string): Triple {
  const v = hex.replace('#', '')
  return [parseInt(v.slice(0, 2), 16), parseInt(v.slice(2, 4), 16), parseInt(v.slice(4, 6), 16)]
}

function rgbToHex([r, g, b]: Triple): string {
  return `#${[r, g, b].map((c) => c.toString(16).padStart(2, '0')).join('')}`
}

/** The CSS Color 4 matrices. `color-mix(in oklab, …)` interpolates in exactly this
 *  space, so resolving a token here yields the sRGB a browser would paint. */
function rgbToOklab([r, g, b]: Triple): Triple {
  const lr = toLinear(r)
  const lg = toLinear(g)
  const lb = toLinear(b)
  const l = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb)
  const m = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb)
  const s = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb)
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ]
}

function oklabToRgb([L, a, b]: Triple): Triple {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3
  return [
    toChannel(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    toChannel(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    toChannel(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ]
}

function relativeLuminance([r, g, b]: Triple): number {
  return 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b)
}

/** WCAG 2.x contrast ratio, order-independent. Same formula as tokens.test.ts. */
function contrastRatio(hexA: string, hexB: string): number {
  const a = relativeLuminance(hexToRgb(hexA))
  const b = relativeLuminance(hexToRgb(hexB))
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

const LANDING_DECLARATION = /--landing-[\w-]+\s*:\s*[^;]+;/g
// `--landing-cell` and `--landing-step` are lengths, `--landing-grid` a line mixed toward
// transparent: none is a text colour, and the resolver below is only for those.
const MIX = /^color-mix\(in oklab,\s*var\((--color-[\w-]+)\)\s*(\d+)%,\s*#ffffff\)$/
const VAR = /^var\((--color-[\w-]+)\)$/

function declaredValue(token: string): string {
  const match = landingCss.match(new RegExp(`${token}\\s*:\\s*([^;]+);`))
  const value = match?.[1]
  if (!value) throw new Error(`${token} is not declared in landing.css`)
  return value.trim()
}

/** Resolves a --landing-* colour token to the sRGB hex a browser would compute. */
function resolveLandingColour(token: string): string {
  const value = declaredValue(token)
  const direct = VAR.exec(value)
  if (direct) {
    const hex = shared[direct[1] ?? '']
    if (!hex) throw new Error(`${token} points at ${direct[1]}, which tokens.css does not define`)
    return hex
  }
  const mixed = MIX.exec(value)
  if (mixed) {
    const hex = shared[mixed[1] ?? '']
    if (!hex) throw new Error(`${token} mixes ${mixed[1]}, which tokens.css does not define`)
    const share = Number(mixed[2]) / 100
    const from = rgbToOklab(hexToRgb(hex))
    const to = rgbToOklab([255, 255, 255])
    return rgbToHex(
      oklabToRgb([
        from[0] * share + to[0] * (1 - share),
        from[1] * share + to[1] * (1 - share),
        from[2] * share + to[2] * (1 - share),
      ]),
    )
  }
  throw new Error(`${token} is neither var(--color-…) nor a color-mix of one: ${value}`)
}

describe('landing tokens', () => {
  it('resolves every --landing-* colour out of the shared palette', () => {
    expect(resolveLandingColour('--landing-surface')).toBe('#f4fffd')
    expect(resolveLandingColour('--landing-ink')).toBe('#011936')
    expect(resolveLandingColour('--landing-ink-quiet')).toBe('#465362')
    expect(resolveLandingColour('--landing-cta')).toBe('#e5133e')
    expect(resolveLandingColour('--landing-focus')).toBe('#ed254e')
  })

  it('contains no raw hexadecimal in the --landing-* block, other than white', () => {
    // White is the neutral a tint is mixed toward, not a sixth colour. Everything
    // else must be a var(--color-…) or a color-mix() of one, which is what makes
    // forking the palette mechanically impossible rather than discouraged.
    for (const declaration of landingCss.match(LANDING_DECLARATION) ?? []) {
      for (const hex of declaration.match(/#[0-9a-fA-F]{3,8}\b/g) ?? []) {
        expect(hex.toLowerCase(), `raw hex in ${declaration}`).toBe('#ffffff')
      }
    }
  })

  it('reaches 4.5:1 on every text pair', () => {
    const surface = resolveLandingColour('--landing-surface')
    const ink = resolveLandingColour('--landing-ink')
    const quiet = resolveLandingColour('--landing-ink-quiet')
    // Boxes and cards are opaque white, so every text colour is also read on white.
    for (const [text, background] of [
      [ink, surface],
      [quiet, surface],
      [ink, '#ffffff'],
      [quiet, '#ffffff'],
      ['#ffffff', resolveLandingColour('--landing-cta')],
    ] as const) {
      expect(contrastRatio(text, background), `${text} on ${background}`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('reaches 3:1 on the focus ring, which is a component and not text', () => {
    const ratio = contrastRatio(
      resolveLandingColour('--landing-focus'),
      resolveLandingColour('--landing-surface'),
    )
    expect(ratio).toBeGreaterThanOrEqual(3)
  })

  it('never uses raw Watermelon as a solid fill', () => {
    // The regression banned by name. In the app this is solved: --primary and
    // --destructive both point at --color-watermelon-strong, because white on raw
    // Watermelon is 4.221:1 and misses the 4.5:1 body-text floor. The landing must
    // not re-introduce it on the one element that IS a solid fill under white
    // text: the call to action.
    for (const [, property, value] of landingCss.matchAll(
      /(?:^|[;{])\s*(background|background-color|fill)\s*:\s*([^;}]+)/g,
    )) {
      expect(value, `${property} fills with raw Watermelon`).not.toMatch(
        /--color-watermelon(?!-strong)/,
      )
      expect(value, `${property} fills with #ed254e`).not.toMatch(/#ed254e/i)
    }
  })

  it('loads no webfont other than Outfit, and none from a CDN', () => {
    expect(landingCss).not.toMatch(/Reenie/i)
    expect(landingCss).not.toMatch(/fonts\.googleapis\.com|fonts\.gstatic\.com/)
    const families = [...landingCss.matchAll(/@font-face\s*\{[^}]*font-family:\s*'([^']+)'/g)].map(
      (m) => m[1],
    )
    expect(families).toEqual(['Outfit'])
  })
})
