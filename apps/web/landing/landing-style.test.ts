import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(join(__dirname, 'landing.css'), 'utf-8')

/** The declarations of one rule, by exact selector. */
function rule(selector: string): string {
  const escaped = selector.replace(/[.[\]*+?^${}()|\\]/g, '\\$&')
  const body = css.match(new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`))?.[1]
  if (!body) throw new Error(`rule "${selector}" not found in landing.css`)
  return body
}

describe('the landing soft layer', () => {
  it('defaults every border away, the way the app does not', () => {
    // The app separates with --border everywhere. The landing separates with the
    // tint of the surface and with space; any visible line is a hairline.
    expect(rule('*')).toMatch(/border-width:\s*0/)
    expect(css).not.toMatch(/var\(--border\)/)
  })

  it('never uses backdrop-filter', () => {
    // the previous system puts blur(12px) on .panel (App.css:166-172). It costs GPU on a phone,
    // and on a static page there is nothing behind the surface worth blurring.
    expect(css).not.toMatch(/backdrop-filter/)
  })

  it('lays the grain under the content, in two stacked pseudo-elements', () => {
    expect(rule('.grain::before').match(/radial-gradient/g)).toHaveLength(3)
    expect(rule('.grain::after')).toMatch(/repeating-linear-gradient\(\s*120deg/)
    expect(rule('.grain::after')).toMatch(/opacity:\s*0\.12/)
    expect(rule('.grain::after')).toMatch(/pointer-events:\s*none/)
    for (const selector of ['.grain::before', '.grain::after']) {
      expect(rule(selector)).toMatch(/z-index:\s*-\d/)
    }
  })

  it('turns the grain off when the reader asked for more contrast', () => {
    // The hatching sits above the background and below the text, so under
    // prefers-contrast: more it is contrast taken away.
    const block = css.match(/@media \(prefers-contrast: more\)\s*\{([\s\S]*?)\n\}/)?.[1] ?? ''
    expect(block).toMatch(/\.grain::before/)
    expect(block).toMatch(/\.grain::after/)
    expect(block).toMatch(/display:\s*none/)
  })

  it('uses only the shipped radius scale, plus the pill for the CTA', () => {
    for (const [, value] of css.matchAll(/border-radius:\s*([^;]+);/g)) {
      expect(value ?? '').not.toBe('')
      expect((value ?? '').trim()).toMatch(
        /^var\(--radius-(?:2xl|3xl|4xl|md|lg)\)$|^var\(--landing-radius-pill\)$/,
      )
    }
    expect(rule('.cta')).toMatch(/border-radius:\s*var\(--landing-radius-pill\)/)
  })

  it('gives sections a wider rhythm than the app and a 62ch measure', () => {
    expect(rule('.section')).toMatch(/padding-block:\s*clamp\(4rem,\s*10vw,\s*9rem\)/)
    expect(rule('.measure')).toMatch(/max-width:\s*62ch/)
  })

  it('carries the previous system overlines verbatim', () => {
    // App.css:88-94. A small detail that does much of the work of that system's
    // character.
    expect(rule('.overline')).toMatch(/text-transform:\s*uppercase/)
    expect(rule('.overline')).toMatch(/letter-spacing:\s*0\.24em/)
    expect(rule('.overline')).toMatch(/font-size:\s*0\.75rem/)
  })

  it('shortens the previous system rise from 0.6s to 320ms and stages it 60ms apart', () => {
    expect(rule('.rise')).toMatch(/320ms/)
    expect(rule('.rise')).toMatch(/cubic-bezier\(0\.2,\s*0\.7,\s*0\.2,\s*1\)/)
    expect(css).toMatch(/--rise-stagger:\s*60ms/)
  })

  it('hides only under an attribute a script has to add', () => {
    // The rule that matters: the initial state is visible. CSS that hides and JS
    // that reveals gives a blank page whenever the script does not run.
    expect(rule('.rise[data-hidden]')).toMatch(/opacity:\s*0/)
    expect(rule('.rise[data-hidden]')).toMatch(/translateY\(12px\)/)
    expect(rule('.rise')).not.toMatch(/opacity:\s*0\b/)
  })

  it('cancels the motion entirely when the reader asked for less of it', () => {
    const block = css.match(/@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*?)\n\}/)?.[1] ?? ''
    expect(block).toMatch(/\.rise/)
    expect(block).toMatch(/transition:\s*none/)
    expect(block).toMatch(/transform:\s*none/)
    expect(block).toMatch(/opacity:\s*1/)
  })

  it('has no scroll-linked transform anywhere', () => {
    // No parallax: it fights the reader and it costs on a phone.
    expect(css).not.toMatch(/animation-timeline|scroll\(\)|view\(\)/)
  })
})
