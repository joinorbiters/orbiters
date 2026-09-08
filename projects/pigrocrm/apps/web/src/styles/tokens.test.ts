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

/* --- Oklab, so the chart tokens can be *computed* rather than recorded by hand ---
   The five --chart-* tokens are `color-mix(in oklab, ...)` expressions, and a test that
   only carried their expected sRGB values as a comment ("recompute these in a browser if
   the expression changes") is a pair that drifts the first time nobody does. Everything
   below is the CSS Color 4 definition of that mix, verified against Chromium's own
   `getComputedStyle` output for all five expressions -- it agrees to the byte. */

const srgbToLinear = (c: number): number =>
  c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
const linearToSrgb = (c: number): number =>
  c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055

type Triple = [number, number, number]

function hexToLinear(hex: string): Triple {
  return hexToRgb(hex).map((c) => srgbToLinear(c / 255)) as Triple
}

function linearToOklab([r, g, b]: Triple): Triple {
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ]
}

function oklabToLinear([lightness, a, b]: Triple): Triple {
  const l = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
  const m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
  const s = (lightness - 0.0894841775 * a - 1.291485548 * b) ** 3
  return [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ]
}

function linearToHex(linear: Triple): string {
  return `#${linear
    .map((c) => Math.round(Math.min(1, Math.max(0, linearToSrgb(c))) * 255).toString(16).padStart(2, '0'))
    .join('')}`
}

function oklabOf(hex: string): Triple {
  return linearToOklab(hexToLinear(hex))
}

/** Euclidean distance in Oklab x100 — the same units the dataviz palette gates use. */
function deltaE(hexA: string, hexB: string): number {
  const a = oklabOf(hexA)
  const b = oklabOf(hexB)
  return Math.hypot(...a.map((v, i) => (v - b[i]!) * 100))
}

/** A colour as it may appear inside a `color-mix()`: a tint reference or a literal. */
function resolveMixOperand(text: string): string {
  const reference = text.match(/^var\(--color-([a-z-]+)\)$/)
  if (reference) return tokenHex(reference[1]!)
  if (/^#[0-9a-fA-F]{6}$/.test(text)) return text
  throw new Error(`unresolvable colour operand in tokens.css: ${text}`)
}

const OPERAND = String.raw`(?:var\(--color-[a-z-]+\)|#[0-9a-fA-F]{6})`

/**
 * Evaluates `color-mix(in oklab, <a> <p>%, <b>)` exactly as a browser does, so the
 * recorded sRGB value of every chart token is derived from the declaration in
 * `tokens.css` instead of asserted against a number somebody typed.
 */
function evaluateChartToken(token: string): string {
  const declaration = css.match(new RegExp(`${token}:\\s*([^;]+);`))
  if (!declaration) throw new Error(`${token} not found in tokens.css`)
  const mix = declaration[1]!
    .trim()
    .match(new RegExp(String.raw`^color-mix\(in oklab,\s*(${OPERAND})\s+(\d{1,3})%,\s*(${OPERAND})\s*\)$`))
  if (!mix) throw new Error(`${token} is not a two-operand oklab color-mix: ${declaration[1]}`)
  const first = oklabOf(resolveMixOperand(mix[1]!))
  const second = oklabOf(resolveMixOperand(mix[3]!))
  const weight = parseInt(mix[2]!, 10) / 100
  const mixed = first.map((v, i) => v * weight + second[i]! * (1 - weight)) as Triple
  return linearToHex(oklabToLinear(mixed))
}

describe('design tokens', () => {
  it.each([
    ['watermelon', '#ed254e'],
    ['watermelon-strong', '#e5133e'],
    ['royal-gold', '#f9dc5c'],
    ['paper', '#f1f2f3'],
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

  it('loads no webfont other than Outfit', () => {
    // `Reenie Beanie` was reserved for the landing page in slice 1B. Slice 5
    // decided it belongs to neither stylesheet: a second webfont is another
    // request and another licence check, it is illegible at small sizes, and a
    // handwritten accent on a page Google reads during OAuth verification looks
    // unserious. landing/landing-tokens.test.ts asserts the same for the other
    // stylesheet, so neither can regain it quietly.
    expect(css).not.toMatch(/Reenie/i)
    const families = [...css.matchAll(/@font-face\s*\{[^}]*font-family:\s*'([^']+)'/g)].map((m) => m[1])
    expect(families).toEqual(['Outfit'])
  })

  const CHART_TOKENS = ['--chart-1', '--chart-2', '--chart-3', '--chart-4', '--chart-5']

  it('declares five chart tokens', () => {
    for (const token of CHART_TOKENS) {
      expect(css).toContain(`${token}:`)
    }
  })

  it('builds every chart token out of existing tints, with no raw hex but white', () => {
    // The mechanical half of "tokens.css stays the single source of colour" (slice 5 §9.3's
    // rule, extended here). `#ffffff` is the one literal permitted: it is the neutral being
    // mixed toward, not a sixth tint.
    for (const token of CHART_TOKENS) {
      const declaration = css.match(new RegExp(`${token}:\\s*([^;]+);`))
      expect(declaration).not.toBeNull()
      const value = declaration![1]!
      expect(value).toContain('color-mix(')
      expect(value).toContain('var(--color-')
      const hexes = value.match(/#[0-9a-fA-F]{3,8}/g) ?? []
      expect(hexes.every((hex) => hex.toLowerCase() === '#ffffff')).toBe(true)
    }
  })

  it('declares the chart tokens outside every @theme block', () => {
    // A @theme entry holding a color-mix() of a var() cannot be resolved into Tailwind
    // utilities at build time, which is what @theme's literal hexes are for. The chart
    // tokens are read as var(--chart-n) in inline styles only.
    // Both @theme blocks are checked, not only the first: `@theme inline` further down
    // registers the semantic slots, and a chart token misfiled there would be just as
    // unresolvable while a first-block-only check waved it through.
    const blocks = [...css.matchAll(/@theme[^{]*\{([^}]*)\}/g)].map((match) => match[1]!)
    expect(blocks.length).toBeGreaterThanOrEqual(2)
    for (const block of blocks) {
      for (const token of CHART_TOKENS) {
        expect(block).not.toContain(token)
      }
    }
  })

  /**
   * The sRGB each chart token resolves to. Not typed in from a browser and trusted: the
   * test beside this derives the same five values from the declarations in `tokens.css`,
   * so an edit to an expression fails here instead of quietly invalidating every contrast
   * assertion below it. Verified once against Chromium's own `getComputedStyle`.
   */
  const CHART_HEX: Record<string, string> = {
    '--chart-1': '#f86774',
    '--chart-2': '#3f526a',
    '--chart-3': '#d6c265',
    '--chart-4': '#616c79',
    '--chart-5': '#5f2e44',
  }

  it('resolves each chart token to the sRGB value the contrast checks below assume', () => {
    for (const [token, hex] of Object.entries(CHART_HEX)) {
      expect(evaluateChartToken(token), token).toBe(hex)
    }
  })

  it('keeps every chart colour visible on both app backgrounds, and a proper mark on one', () => {
    // Read this with the WARN it records. 3:1 -- WCAG's threshold for a graphical object,
    // not for body text -- is what a chart mark carrying meaning must clear, and these five
    // do not clear it on both surfaces: --chart-1 measures 2.86:1 on the light background,
    // --chart-3 1.75:1, --chart-2 2.20:1 on the dark one and --chart-5 1.64:1. That is a
    // consequence of the expressions, which are fixed by the plan's token table, and of
    // there being one set of five for both modes.
    //
    // It is legal here, and only here, because **colour encodes nothing in these shapes**:
    // every bar sits in its own row with its label and its value as text, and every chart
    // renders an equivalent table that is the accessible rendering (§13). The mark is
    // decoration on top, `aria-hidden`, and a reader who cannot separate two hues has lost
    // no information. Introduce a shape where colour is the only thing telling two series
    // apart -- a legend-keyed multi-series line, a stacked bar without direct labels -- and
    // this test is no longer the right gate: raise it to 3:1 on both surfaces and re-step
    // the tokens, rather than relaxing the shape.
    //
    // What is still asserted, because it must hold for decoration too: each colour is a
    // real mark against at least one surface, and never sinks into either one.
    const light = tokenHex('paper')
    const dark = tokenHex('prussian-blue')
    for (const [token, hex] of Object.entries(CHART_HEX)) {
      const onLight = contrastRatio(hex, light)
      const onDark = contrastRatio(hex, dark)
      expect(Math.max(onLight, onDark), `${token} on its better surface`).toBeGreaterThanOrEqual(3)
      // 1.5:1 is the floor below which a fill stops reading as a shape at all. The measured
      // worst is --chart-5 on the dark background at 1.64:1; this is the ratchet that keeps
      // a future edit from spending that headroom.
      expect(Math.min(onLight, onDark), `${token} on its worse surface`).toBeGreaterThanOrEqual(1.5)
    }
  })

  it('keeps the five chart colours distinguishable from each other', () => {
    // Five bars a reader cannot tell apart is one bar drawn five times.
    const computed = CHART_TOKENS.map((token) => CHART_HEX[token]!)
    for (let i = 0; i < computed.length; i += 1) {
      for (let j = i + 1; j < computed.length; j += 1) {
        expect(contrastRatio(computed[i]!, computed[j]!)).toBeGreaterThanOrEqual(1.2)
      }
    }
  })

  it('separates every pair of chart colours by perceptual distance, not only by lightness', () => {
    // A contrast ratio is a lightness comparison: it scores two colours of the same
    // luminance and different hue as identical, so the check above passes palettes that
    // collapse. Oklab ΔE is the measure that does not.
    //
    // ΔE ≥ 8 is the categorical target when colour carries identity; ≥ 15 is the
    // normal-vision floor for that case. This palette's worst pair is --chart-2 against
    // --chart-4 (#3f526a / #616c79) at ΔE 9.6 -- two slates one derivation apart, both
    // unavoidable given a brand of two saturated hues and two near-neutral blues. It is
    // below that floor and stays there for the same reason the contrast WARN above stands:
    // identity is carried by the row label and the table, never by the hue.
    // 9 is the ratchet under the measured worst pair.
    const computed = CHART_TOKENS.map((token) => CHART_HEX[token]!)
    for (let i = 0; i < computed.length; i += 1) {
      for (let j = i + 1; j < computed.length; j += 1) {
        expect(
          deltaE(computed[i]!, computed[j]!),
          `${CHART_TOKENS[i]} vs ${CHART_TOKENS[j]}`,
        ).toBeGreaterThanOrEqual(9)
      }
    }
  })
})

/* --- The soft-shape system (2026-09-08 app UI revision, design spec §3) ---
   Until 2026-09-07 the app shared Orbiters' pixel system: zero radius, a 24% line, a
   step shadow of solid ink, a grid on the body. The app now has its own shapes -- 10px
   radius, a 12% line, low-opacity blurred shadows, no grid -- while the landing and
   Orbiters keep the pixel system in their own stylesheets. These assertions pin the
   numbers so a future edit has to mean it. */
describe('soft shapes', () => {
  /** The declarations of one rule of tokens.css, by exact selector. */
  function block(selector: string): string {
    const escaped = selector.replace(/[.[\]*+?^${}()|\\]/g, '\\$&')
    const body = css.match(new RegExp(`(?:^|\\n)${escaped}\\s*\\{([\\s\\S]*?)\\n\\}`))?.[1]
    if (!body) throw new Error(`rule "${selector}" not found in tokens.css`)
    return body
  }

  it('derives every radius from a single 10px --radius', () => {
    // 10px keeps the buttons at 10 and the derived scale where the reference sits:
    // --radius-lg 10, --radius-xl 14, --radius-2xl 18.
    expect(css).toMatch(/--radius:\s*10px/)
    expect(css).toMatch(/--radius-lg:\s*var\(--radius\)/)
    expect(css).toMatch(/--radius-xl:\s*calc\(var\(--radius\) \* 1\.4\)/)
    expect(css).toMatch(/--radius-2xl:\s*calc\(var\(--radius\) \* 1\.8\)/)
  })

  it('draws lines at 12% of the ink and input borders at 20%', () => {
    // The reference separates with near-invisible lines and with space. 24%/32% was
    // the pixel system's hard edge.
    expect(block(':root')).toMatch(
      /--border:\s*color-mix\(in oklab, var\(--color-prussian-blue\) 12%, #ffffff\)/,
    )
    expect(block(':root')).toMatch(
      /--input:\s*color-mix\(in oklab, var\(--color-prussian-blue\) 20%, #ffffff\)/,
    )
    // Dark mode fades the paper into the ink by the same two steps.
    expect(block('.dark')).toMatch(/--border:\s*color-mix\(in oklab, var\(--color-paper\) 12%,/)
    expect(block('.dark')).toMatch(/--input:\s*color-mix\(in oklab, var\(--color-paper\) 20%,/)
  })

  /** The value one token is assigned inside one rule, by exact selector. */
  function declaration(selector: string, token: string): string {
    const value = block(selector).match(new RegExp(`${token}:\\s*([^;]+);`))?.[1]
    if (!value) throw new Error(`${token} is not declared in "${selector}"`)
    return value.trim()
  }

  it('builds the quiet surfaces out of the palette, in both modes', () => {
    // `--muted` is the table's hover and every quiet fill; `--secondary` the secondary
    // button and badge. Until this pass both were hand-mixed hexes -- #eef4f2 and #e6ecea
    // in light mode -- with the same green-cyan cast the page background lost on
    // 2026-09-08 ("azzurrino"), and belonging to no tint in the palette. A tint, or a mix
    // of tints toward white, is all either may be.
    for (const selector of [':root', '.dark']) {
      for (const token of ['--muted', '--secondary']) {
        const value = declaration(selector, token)
        expect(value, `${token} in ${selector}`).toMatch(
          /^(?:var\(--color-[a-z-]+\)|color-mix\(in oklab,)/,
        )
        for (const hex of value.match(/#[0-9a-fA-F]{3,8}/g) ?? []) {
          expect(hex.toLowerCase(), `hex in ${token} (${selector})`).toBe('#ffffff')
        }
        for (const [, name] of value.matchAll(/var\(--([a-z0-9-]+)\)/g)) {
          expect(name, `var in ${token} (${selector})`).toMatch(/^color-/)
        }
      }
    }
  })

  it('makes the quiet fill Paper itself, which is what a table row hover has to be', () => {
    // Spec §4 says the hover is Paper, and `ui/table.tsx` draws it as `hover:bg-muted`.
    // The two only agree while this token *is* Paper.
    expect(declaration(':root', '--muted')).toBe('var(--color-paper)')
  })

  const SHADOWS = ['xs', 'sm', 'md', 'lg', 'xl', '2xl']

  it('casts soft ink shadows, never a step', () => {
    for (const step of SHADOWS) {
      const declaration = css.match(new RegExp(`--shadow-${step}:\\s*([^;]+);`))
      expect(declaration, `--shadow-${step}`).not.toBeNull()
      const value = declaration![1]!.trim()
      // `0 <y> <blur> var(--shadow-ink*)`: no horizontal offset (the step's signature),
      // a real blur radius, and the colour read from one of the three ink tokens.
      expect(value, `--shadow-${step}`).toMatch(
        /^0 \d+px \d+px var\(--shadow-ink(?:-weak|-strong)?\)$/,
      )
    }
  })

  it('keeps the shadow ink a low-opacity tint of the ink itself', () => {
    // 6-12% in light mode: the reference lifts a menu off the page, it does not
    // draw it a border of shadow. Dark mode needs more ink to read at all.
    const light = block(':root')
    expect(light).toMatch(/--shadow-ink-weak:\s*color-mix\(in oklab, var\(--color-prussian-blue\) 6%, transparent\)/)
    expect(light).toMatch(/--shadow-ink:\s*color-mix\(in oklab, var\(--color-prussian-blue\) 8%, transparent\)/)
    expect(light).toMatch(/--shadow-ink-strong:\s*color-mix\(in oklab, var\(--color-prussian-blue\) 12%, transparent\)/)
    for (const name of ['--shadow-ink-weak', '--shadow-ink', '--shadow-ink-strong']) {
      expect(block('.dark'), name).toContain(`${name}: color-mix(`)
    }
    // The step colour token the pixel system cast its shadows in is gone with it.
    expect(css).not.toMatch(/--step:/)
  })

  it('points the sidebar at the Prussian Blue menu of the reference', () => {
    const light = block(':root')
    expect(light).toMatch(/--sidebar:\s*var\(--color-prussian-blue\)/)
    expect(light).toMatch(/--sidebar-foreground:\s*var\(--color-paper\)/)
    expect(light).toMatch(/--sidebar-accent:\s*color-mix\(in oklab, #ffffff 10%, var\(--color-prussian-blue\)\)/)
    expect(light).toMatch(/--sidebar-accent-foreground:\s*#ffffff/)
    expect(light).toMatch(/--sidebar-border:\s*color-mix\(in oklab, #ffffff 12%, var\(--color-prussian-blue\)\)/)
    // Watermelon-strong, not raw Watermelon: the sidebar now renders white on it.
    expect(light).toMatch(/--sidebar-primary:\s*var\(--color-watermelon-strong\)/)
  })

  it('carries Paper text on the menu at AA', () => {
    // The one contrast pair the dark menu introduces.
    expect(contrastRatio(tokenHex('paper'), tokenHex('prussian-blue'))).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio('#ffffff', tokenHex('watermelon-strong'))).toBeGreaterThanOrEqual(4.5)
  })

  it('no longer draws the grid on the app body', () => {
    // The white content panel covers the page, and the grid was the tie to Orbiters.
    // system.css stays the single declaration of the line and tile, for the landing
    // and Orbiters, which do not change (landing/landing-style.test.ts).
    expect(css).not.toMatch(/--grid-line/)
    expect(css).not.toMatch(/background-image:/)
    expect(css).not.toMatch(/background-size:/)
  })

  it('mixes only the five tints, white and transparent, everywhere in the file', () => {
    // The chart tokens had this rule; the border, input, sidebar and shadow tokens
    // are color-mix()es too now, so it applies to every mix in the file. A sixth
    // colour cannot enter through one of them.
    const mixes = [...css.matchAll(/color-mix\(in oklab,([^;]*?)\)\s*(?:;|,)/g)].map((m) => m[1]!)
    expect(mixes.length).toBeGreaterThan(10)
    for (const mix of mixes) {
      for (const hex of mix.match(/#[0-9a-fA-F]{3,8}/g) ?? []) {
        expect(hex.toLowerCase(), `hex inside color-mix(${mix})`).toBe('#ffffff')
      }
      for (const [, name] of mix.matchAll(/var\(--([a-z0-9-]+)\)/g)) {
        expect(name, `var inside color-mix(${mix})`).toMatch(/^color-/)
      }
    }
  })
})
