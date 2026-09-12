import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('posthog-js', () => ({
  default: {
    init: vi.fn(),
    identify: vi.fn(),
    group: vi.fn(),
    capture: vi.fn(),
    reset: vi.fn(),
    setInternalOrTestUser: vi.fn(),
  },
}))

import posthog from 'posthog-js'
import {
  __resetAnalyticsForTests,
  analyticsActive,
  capture,
  identifyGroup,
  identifyUser,
  initAnalytics,
  resetUser,
} from './browser'
import { POSTHOG_HOST, POSTHOG_KEY } from './posthog'

const init = vi.mocked(posthog.init)

beforeEach(() => {
  vi.clearAllMocks()
  __resetAnalyticsForTests()
})

afterEach(() => {
  __resetAnalyticsForTests()
})

describe('on a developer machine', () => {
  it('initialises nothing and every call is a no-op', () => {
    expect(initAnalytics({ hostname: 'localhost' })).toBe(false)
    expect(analyticsActive()).toBe(false)
    identifyUser('u1', { email: 'a@b.it' })
    identifyGroup('spazio', 'root')
    capture('cliente_creato')
    resetUser()
    expect(init).not.toHaveBeenCalled()
    expect(posthog.identify).not.toHaveBeenCalled()
    expect(posthog.group).not.toHaveBeenCalled()
    expect(posthog.capture).not.toHaveBeenCalled()
    expect(posthog.reset).not.toHaveBeenCalled()
  })
})

describe('on a real host', () => {
  it('initialises the shared project with the shared policy', () => {
    expect(initAnalytics({ hostname: 'pigro.joinorbiters.com' })).toBe(true)
    expect(analyticsActive()).toBe(true)
    expect(init).toHaveBeenCalledTimes(1)
    const [key, config] = init.mock.calls[0] ?? []
    expect(key).toBe(POSTHOG_KEY)
    expect(config).toMatchObject({
      api_host: POSTHOG_HOST,
      person_profiles: 'identified_only',
      // TanStack Router pushes history: a SPA has to count the pages navigated to, not
      // only the full loads. Both are the 2026-08-30 defaults too; they are written out
      // so the policy reads without knowing what a date implies.
      capture_pageview: 'history_change',
      autocapture: true,
    })
    expect(config?.session_recording).toMatchObject({ maskAllInputs: true })
    // A real host is a visitor, not one of us.
    expect(posthog.setInternalOrTestUser).not.toHaveBeenCalled()
  })

  it('marks the preview stacks as internal, so their events exist and can be filtered out', () => {
    // As a call, not as the `internal_or_test_user_hostname` option: the SDK's defaults
    // overwrote that option live (browser.ts says where and when).
    expect(initAnalytics({ hostname: 'preview.pigro.joinorbiters.com' })).toBe(true)
    expect(posthog.setInternalOrTestUser).toHaveBeenCalledTimes(1)
    expect(init.mock.calls[0]?.[1]).not.toHaveProperty('internal_or_test_user_hostname')
  })

  it('masks every text node only when asked, which is what the CRM asks', () => {
    initAnalytics({ hostname: 'pigro.joinorbiters.com', maskText: true })
    expect(init.mock.calls[0]?.[1]?.session_recording?.maskTextSelector).toBe('*')
    vi.clearAllMocks()
    __resetAnalyticsForTests()
    initAnalytics({ hostname: 'joinorbiters.com' })
    expect(init.mock.calls[0]?.[1]?.session_recording).not.toHaveProperty('maskTextSelector')
  })

  it('passes identify, group, capture and reset through', () => {
    initAnalytics({ hostname: 'pigro.joinorbiters.com' })
    identifyUser('u1', { email: 'a@b.it', nome: 'Ada' })
    identifyGroup('spazio', 'studio', { nome: 'Studio' })
    capture('cliente_creato', { via: 'ui' })
    resetUser()
    expect(posthog.identify).toHaveBeenCalledWith('u1', { email: 'a@b.it', nome: 'Ada' })
    expect(posthog.group).toHaveBeenCalledWith('spazio', 'studio', { nome: 'Studio' })
    expect(posthog.capture).toHaveBeenCalledWith('cliente_creato', { via: 'ui' })
    expect(posthog.reset).toHaveBeenCalledTimes(1)
  })
})
