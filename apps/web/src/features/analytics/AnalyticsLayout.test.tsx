/**
 * The Analisi shell: one intestazione, three tabs, and the tab the URL names marked as
 * the current one.
 *
 * Modelled on `features/settings/SettingsLayout.test.tsx`, the sibling layout with the
 * same shape -- and mocked the same way, because what is under test is this component's
 * own reading of the pathname, not TanStack's routing. `Outlet` is a stub so the test
 * can tell "the layout rendered its child route" from "the layout rendered a panel of
 * its own", and `Link` an `<a>` so the tab triggers keep their `href` to assert on.
 *
 * There is no admin gate to test here, unlike Settings: Margini and
 * Preventivo/consuntivo are ordinary reads, and the fiscal estimate surfaces the
 * server's own refusal inside its panel rather than hiding the tab (see the component's
 * docstring).
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AnalyticsLayout } from './AnalyticsLayout'

const mockLocation = vi.hoisted(() => ({ pathname: '/app/analisi/margini' }))

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return {
    ...actual,
    Link: ({ children, to, ...props }: { children: React.ReactNode; to?: string }) => (
      <a href={to} {...props}>
        {children}
      </a>
    ),
    Outlet: () => <div data-testid="outlet-content" />,
    useRouterState: () => ({ location: mockLocation }),
  }
})

describe('AnalyticsLayout', () => {
  it('opens with its title as the page heading, and only one', () => {
    // The shell has had no top bar since the 2026-09-08 revision, so this `<h1>` is the
    // only thing naming the screen -- and a second one would mean the layout and a panel
    // were both claiming to title the page.
    mockLocation.pathname = '/app/analisi/margini'
    render(<AnalyticsLayout />)
    expect(screen.getByRole('heading', { level: 1, name: 'Analisi' })).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  })

  it('renders the three tabs and the active child route', () => {
    mockLocation.pathname = '/app/analisi/margini'
    render(<AnalyticsLayout />)
    expect(screen.getByRole('tab', { name: 'Margini' })).toHaveAttribute(
      'href',
      '/app/analisi/margini',
    )
    expect(screen.getByRole('tab', { name: 'Preventivo/consuntivo' })).toHaveAttribute(
      'href',
      '/app/analisi/preventivo-consuntivo',
    )
    expect(screen.getByRole('tab', { name: 'Fiscale' })).toHaveAttribute(
      'href',
      '/app/analisi/fiscale',
    )
    expect(screen.getByTestId('outlet-content')).toBeInTheDocument()
  })

  it('marks the tab the URL names, not the first one', () => {
    mockLocation.pathname = '/app/analisi/fiscale'
    render(<AnalyticsLayout />)
    expect(screen.getByRole('tab', { name: 'Fiscale' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByRole('tab', { name: 'Margini' })).toHaveAttribute(
      'aria-selected',
      'false',
    )
  })

  /** A pathname that matches no tab -- a stale link, or the bare `/app/analisi` before
   *  its own redirect fires -- must still mark something, or the row reads as a page
   *  with no current tab. */
  it('falls back to Margini for a pathname that names no tab', () => {
    mockLocation.pathname = '/app/analisi'
    render(<AnalyticsLayout />)
    expect(screen.getByRole('tab', { name: 'Margini' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })
})
