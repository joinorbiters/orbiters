import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { extractSharedTokens } from './palette-plugin'

const tokensCss = readFileSync(fileURLToPath(import.meta.resolve('@orbiters/brand/palette.css')), 'utf-8')

describe('extractSharedTokens', () => {
  it('extracts exactly the seven tokens the brand shares: six colours and the typeface', () => {
    expect(Object.keys(extractSharedTokens(tokensCss)).sort()).toEqual([
      '--color-charcoal-blue',
      '--color-paper',
      '--color-prussian-blue',
      '--color-royal-gold',
      '--color-watermelon',
      '--color-watermelon-strong',
      '--font-sans',
    ])
  })

  it('carries the live hex, so an edit to the palette travels with it', () => {
    expect(extractSharedTokens(tokensCss)['--color-watermelon-strong']).toBe('#e5133e')
  })

  it('drops indirections rather than emitting dangling var() references', () => {
    // The guard that matters now that the palette is a package of its own: a token
    // whose value points at something the landing never receives would inject a
    // colour resolving to nothing. The application's `@theme inline` re-exports
    // (--color-primary: var(--primary) and 25 siblings) and its radius scale used to
    // arrive here for exactly that reason, and the landing used none of them.
    const extracted = extractSharedTokens(tokensCss)
    expect(extracted['--color-primary']).toBeUndefined()
    expect(extracted['--radius-2xl']).toBeUndefined()
    for (const value of Object.values(extracted)) {
      for (const [, referenced] of value.matchAll(/var\((--[\w-]+)\)/g)) {
        expect(Object.keys(extracted)).toContain(referenced)
      }
    }
  })

  it('refuses a stylesheet that has lost the palette, instead of emitting nothing', () => {
    expect(() => extractSharedTokens('@theme { --color-watermelon: #ed254e; }')).toThrow(
      /extracted only 1 shared token/,
    )
  })
})
