import { describe, expect, it } from 'vitest'
import {
  INTERNAL_HOSTS,
  POSTHOG_ASSET_HOST,
  POSTHOG_HOST,
  POSTHOG_KEY,
  analyticsEnabled,
  isInternalHost,
} from './posthog'

describe('the project', () => {
  it('is one project key, on Cloud EU, with its assets on the EU host too', () => {
    // `phc_` is a project key, which is public and can only write events. A personal
    // key is `phx_` and must never be here: it writes to the whole account.
    expect(POSTHOG_KEY).toMatch(/^phc_[A-Za-z0-9]{20,}$/)
    expect(POSTHOG_KEY).not.toMatch(/^phx_/)
    expect(POSTHOG_HOST).toBe('https://eu.i.posthog.com')
    expect(POSTHOG_ASSET_HOST).toBe('https://eu-assets.i.posthog.com')
  })
})

describe('which hosts send events', () => {
  it('sends nothing from a developer machine or a test runner', () => {
    for (const host of ['localhost', '127.0.0.1', '[::1]', '0.0.0.0', '']) {
      expect(analyticsEnabled(host), host).toBe(false)
    }
  })

  it('sends from every real host, preview included', () => {
    for (const host of [
      'joinorbiters.com',
      'www.joinorbiters.com',
      'pigro.joinorbiters.com',
      'preview.joinorbiters.com',
      'preview.pigro.joinorbiters.com',
    ]) {
      expect(analyticsEnabled(host), host).toBe(true)
    }
  })

  it('marks the two preview stacks as internal and nothing else', () => {
    expect(isInternalHost('preview.joinorbiters.com')).toBe(true)
    expect(isInternalHost('preview.pigro.joinorbiters.com')).toBe(true)
    expect(isInternalHost('joinorbiters.com')).toBe(false)
    expect(isInternalHost('pigro.joinorbiters.com')).toBe(false)
    // A RegExp, because that is what posthog-js's `internal_or_test_user_hostname`
    // takes for a pattern; a string there would mean exact equality with one host.
    expect(INTERNAL_HOSTS).toBeInstanceOf(RegExp)
  })
})
