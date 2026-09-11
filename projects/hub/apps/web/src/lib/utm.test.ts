import { describe, expect, it } from 'vitest'
import { afterEach, beforeEach } from 'vitest'
import { ORIGIN_STORAGE_KEY, UTM_STORAGE_KEY, readOrigin, readUtm, recallUtm, rememberUtm, resolveAttribution, resolveOrigin, resolveUtm } from './utm'

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

describe('resolveUtm, with what the tab remembers (ORB-166)', () => {
  beforeEach(() => window.sessionStorage.clear())
  afterEach(() => window.sessionStorage.clear())

  it('prefers the URL and remembers it for the tab', () => {
    expect(resolveUtm('?utm_source=linkedin&utm_id=42')).toEqual({ utm_source: 'linkedin', utm_id: '42' })
    expect(window.sessionStorage.getItem(UTM_STORAGE_KEY)).toBe('utm_source=linkedin&utm_id=42')
  })

  it('falls back to what the landing left in the tab when the URL has nothing', () => {
    window.sessionStorage.setItem(UTM_STORAGE_KEY, 'utm_source=linkedin&utm_campaign=orbita&gclid=x')
    expect(resolveUtm('')).toEqual({ utm_source: 'linkedin', utm_campaign: 'orbita' })
    expect(resolveUtm('?perk=guida')).toEqual({ utm_source: 'linkedin', utm_campaign: 'orbita' })
  })

  it('is empty when neither the URL nor the tab knows a campaign', () => {
    expect(resolveUtm('?perk=guida')).toEqual({})
    expect(recallUtm()).toEqual({})
  })

  it('remembers nothing for an empty attribution', () => {
    rememberUtm({})
    expect(window.sessionStorage.getItem(UTM_STORAGE_KEY)).toBeNull()
  })
})

describe('the page the person started from (ORB-167)', () => {
  beforeEach(() => window.sessionStorage.clear())
  afterEach(() => window.sessionStorage.clear())

  it('reads `da=` when it is a slug, and nothing else', () => {
    expect(readOrigin('?da=pigrocrm&utm_source=linkedin')).toBe('pigrocrm')
    expect(readOrigin('?da=home')).toBe('home')
    expect(readOrigin('?da=%3Cscript%3E')).toBeNull()
    expect(readOrigin('?da=')).toBeNull()
    expect(readOrigin('')).toBeNull()
  })

  it('prefers the URL, remembers it for the tab, and falls back to the tab', () => {
    expect(resolveOrigin('?da=pigrocrm')).toBe('pigrocrm')
    expect(window.sessionStorage.getItem(ORIGIN_STORAGE_KEY)).toBe('pigrocrm')
    expect(resolveOrigin('?perk=guida')).toBe('pigrocrm')
    window.sessionStorage.setItem(ORIGIN_STORAGE_KEY, 'not a slug!')
    expect(resolveOrigin('')).toBeNull()
  })

  it('folds the page into the attribution an application sends', () => {
    expect(resolveAttribution('?utm_source=linkedin&da=home')).toEqual({ utm_source: 'linkedin', origine: 'home' })
    window.sessionStorage.clear()
    expect(resolveAttribution('')).toEqual({})
  })
})
