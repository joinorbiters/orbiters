import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(join(__dirname, 'tokens.css'), 'utf-8')

describe('design tokens', () => {
  it.each([
    ['watermelon', '#ed254e'],
    ['royal-gold', '#f9dc5c'],
    ['mint-cream', '#f4fffd'],
    ['prussian-blue', '#011936'],
    ['charcoal-blue', '#465362'],
  ])('defines %s as %s', (name, hex) => {
    expect(css).toContain(`--color-${name}: ${hex}`)
  })

  it('uses Watermelon as the primary action colour', () => {
    expect(css).toMatch(/--primary:\s*var\(--color-watermelon\)/)
  })

  it('defines a dark mode', () => {
    expect(css).toContain('.dark {')
  })

  it('does not load Reenie Beanie, which belongs to the landing page', () => {
    expect(css).not.toMatch(/Reenie/i)
  })
})
