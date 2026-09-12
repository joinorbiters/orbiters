import { describe, expect, it } from 'vitest'
import { readPerkParam } from './analytics'

describe('readPerkParam', () => {
  it('reads the perk as it arrived, and nothing for a blank or absent one', () => {
    expect(readPerkParam('?perk=guida')).toBe('guida')
    expect(readPerkParam('?utm_source=linkedin&perk=guida')).toBe('guida')
    // Unlike the banner, the funnel keeps a value it does not recognise: it happened.
    expect(readPerkParam('?perk=crm')).toBe('crm')
    expect(readPerkParam('?perk=%20')).toBeNull()
    expect(readPerkParam('')).toBeNull()
  })
})
