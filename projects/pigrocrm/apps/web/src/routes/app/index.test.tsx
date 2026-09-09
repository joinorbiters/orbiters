/**
 * The wiring, which is the half of the URL round trip the component tests cannot see.
 *
 * `features/dashboard/periodo.test.ts` proves `validateDashboardSearch` reads a period
 * back; `features/dashboard/DashboardPage.test.tsx` proves the page requests the period it
 * is given and hands a changed one back. Neither notices if the route forgets to declare
 * `validateSearch` at all -- at which point `/app/?da=…` silently becomes the current
 * month for every shared link. That is what this file asserts.
 */
import { describe, expect, it } from 'vitest'
import { validateDashboardSearch } from '@/features/dashboard/search'
import { Route } from './index'

describe('the /app/ route', () => {
  it('validates its search params with the dashboard validator', () => {
    expect(Route.options.validateSearch).toBe(validateDashboardSearch)
  })

  it('is reachable with no search params at all', () => {
    // The dashboard is the landing page. A 404 on the home screen because a query
    // parameter is missing would be absurd, so the validator fills the period in.
    // Called through the route's own options rather than by importing the validator
    // directly, so this asserts what the *router* will run — a route that stopped wiring
    // `validateSearch` would fail here, and would not if the function were called on its
    // own. The cast is needed because `validateSearch` is a union of four shapes
    // (function, object, adapter, standard schema) and only one of them is callable.
    const validate = Route.options.validateSearch as typeof validateDashboardSearch
    const search = validate({})
    expect(search.tab).toBe('economica')
    expect(search.da).toMatch(/^\d{4}-\d{2}-01$/)
  })
})
