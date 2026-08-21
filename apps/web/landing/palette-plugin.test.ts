import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { extractSharedTokens } from './palette-plugin'

const tokensCss = readFileSync(join(__dirname, '../src/styles/tokens.css'), 'utf-8')

describe('extractSharedTokens', () => {
  it('extracts exactly the fifteen tokens the two stylesheets share', () => {
    expect(Object.keys(extractSharedTokens(tokensCss)).sort()).toEqual([
      '--color-charcoal-blue',
      '--color-mint-cream',
      '--color-prussian-blue',
      '--color-royal-gold',
      '--color-watermelon',
      '--color-watermelon-strong',
      '--font-sans',
      '--radius',
      '--radius-2xl',
      '--radius-3xl',
      '--radius-4xl',
      '--radius-lg',
      '--radius-md',
      '--radius-sm',
      '--radius-xl',
    ])
  })

  it('carries the live hex, so an edit to tokens.css travels with it', () => {
    expect(extractSharedTokens(tokensCss)['--color-watermelon-strong']).toBe('#e5133e')
  })

  it('drops the app-only indirections rather than emitting dangling var() references', () => {
    // `@theme inline` re-exports --color-primary: var(--primary) and 25 siblings.
    // --primary is declared in tokens.css's `:root`, which the landing does not
    // import, so injecting them would produce colours resolving to nothing.
    const extracted = extractSharedTokens(tokensCss)
    expect(extracted['--color-primary']).toBeUndefined()
    expect(extracted['--color-background']).toBeUndefined()
    // --radius-2xl also uses var(), but only of a token that IS extracted.
    expect(extracted['--radius-2xl']).toBe('calc(var(--radius) * 1.8)')
  })

  it('refuses a stylesheet that has lost the palette, instead of emitting nothing', () => {
    expect(() => extractSharedTokens('@theme { --color-watermelon: #ed254e; }')).toThrow(
      /extracted only 1 shared token/,
    )
  })
})
