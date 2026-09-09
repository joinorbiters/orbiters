import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { BRAND_TILES, BRAND_TILE_CLASSES } from '@orbiters/brand/mark'

import { BrandMark } from './BrandMark'

/**
 * The mark is the brand's, not this application's: the landing and the community page
 * draw the same four tiles as box-shadows on one element, and Orbiters' favicon is the
 * same field at glyph scale. Three surfaces, three technologies, one order, so each
 * side asserts against `shared/brand` rather than against another surface's source.
 *
 * This assertion used to live in the landing's own suite, where it read this file as
 * text and matched its JSX with a regular expression. That only worked while the two
 * shared a directory; the landing is its own project now, and reading a React
 * component it cannot import is not a dependency worth keeping.
 */
describe('BrandMark', () => {
  it('draws the four brand tiles in reading order', () => {
    const { container } = render(<BrandMark />)
    const tiles = [...container.querySelectorAll('span > span')].map((tile) => tile.className)
    expect(tiles).toEqual(BRAND_TILES.map((tile) => BRAND_TILE_CLASSES[tile]))
  })

  it('is decorative, so assistive technology never announces it', () => {
    // It never carries the name: whatever it sits beside is the accessible text.
    const { container } = render(<BrandMark />)
    expect(container.firstElementChild).toHaveAttribute('aria-hidden', 'true')
  })
})
