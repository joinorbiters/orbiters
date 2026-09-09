import { describe, expect, it } from 'vitest'
import { readUtm } from './utm'

describe('readUtm', () => {
  it('keeps the six UTM keys and nothing else', () => {
    expect(
      readUtm('?utm_source=linkedin&utm_medium=paid&utm_id=123&gclid=x&utm_term=%20'),
    ).toEqual({ utm_source: 'linkedin', utm_medium: 'paid', utm_id: '123' })
  })

  it('stores an unexpanded macro as the literal it was', () => {
    expect(readUtm('?utm_campaign=%7B%7Bcampaign%7D%7D')).toEqual({ utm_campaign: '{{campaign}}' })
  })

  it('is empty for an empty search', () => {
    expect(readUtm('')).toEqual({})
  })
})
