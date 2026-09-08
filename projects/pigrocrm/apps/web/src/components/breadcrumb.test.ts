/**
 * `breadcrumbFor` as a pure function, which is how it was always tested: asserting on
 * rendered crumbs through a router mock cannot tell a routing failure from a labelling
 * one. Its component, `AppHeader`, is gone -- the shell has no top bar since the
 * 2026-09-08 revision (the search moved into the sidebar, the title into `PageHeader`) --
 * so these assertions moved next to the helper itself, which pages can still use for a
 * crumb of their own.
 */
import { describe, expect, it } from 'vitest'
import { breadcrumbFor } from './breadcrumb'

describe('breadcrumbFor', () => {
  it('labels the dashboard root', () => {
    expect(breadcrumbFor('/app')).toEqual(['Dashboard'])
    expect(breadcrumbFor('/app/')).toEqual(['Dashboard'])
  })

  it('labels a known section', () => {
    expect(breadcrumbFor('/app/clienti')).toEqual(['Clienti'])
    expect(breadcrumbFor('/app/impostazioni/campi')).toEqual(['Impostazioni', 'Campi'])
  })

  it('renders a detail route without leaking the id into the crumb', () => {
    expect(breadcrumbFor('/app/clienti/0192f3b2-8c1a-7c3d-9f4e-1a2b3c4d5e6f')).toEqual([
      'Clienti',
      'Dettaglio',
    ])
  })

  it('falls back to a capitalised segment for an unmapped path', () => {
    expect(breadcrumbFor('/app/qualcosa')).toEqual(['Qualcosa'])
  })
})
