import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { EntityDetailLayout } from './EntityDetailLayout'

// `Timeline` makes a real network call through `useQuery` (see Timeline.test.tsx
// for its own coverage) -- irrelevant to what this file is about, which is the
// tab shell around it, so it is stubbed out the same way the task brief itself
// specifies. The stub also records the props it was called with, so the "wiring"
// tests below can confirm the layout actually forwards `entityType`/`entityId`
// rather than only rendering *some* Timeline.
//
// Radix's `TabsContent` does not mount an inactive tab's children at all (not
// merely hide them), so the stub only actually renders -- and `timelineSpy` only
// actually records a call -- once the Timeline tab has been activated at least
// once. The wiring tests below click it first for exactly that reason; every
// other test here never touches the Timeline tab and so never triggers it.
const timelineSpy = vi.fn()
vi.mock('./Timeline', () => ({
  Timeline: (props: unknown) => {
    timelineSpy(props)
    return <div>timeline-stub</div>
  },
}))

beforeEach(() => {
  timelineSpy.mockClear()
})

function renderLayout(overrides: Partial<Parameters<typeof EntityDetailLayout>[0]> = {}) {
  return render(
    <EntityDetailLayout
      title="ACME Srl"
      subtitle="Cliente"
      entityType="customer"
      entityId="abc"
      overview={<p>panoramica</p>}
      links={<p>collegamenti</p>}
      {...overrides}
    />,
  )
}

describe('EntityDetailLayout', () => {
  it('shows the title and subtitle', () => {
    renderLayout()
    expect(screen.getByText('ACME Srl')).toBeInTheDocument()
    expect(screen.getByText('Cliente')).toBeInTheDocument()
  })

  it('exposes the same three tabs for every entity', () => {
    renderLayout()
    for (const tab of ['Panoramica', 'Timeline', 'Collegamenti']) {
      expect(screen.getByRole('tab', { name: tab })).toBeInTheDocument()
    }
  })

  it('opens on Panoramica', () => {
    renderLayout()
    expect(screen.getByText('panoramica')).toBeInTheDocument()
  })

  it('switches to Collegamenti when asked', async () => {
    renderLayout()
    await userEvent.click(screen.getByRole('tab', { name: 'Collegamenti' }))
    expect(screen.getByText('collegamenti')).toBeInTheDocument()
  })

  it('switches to Timeline when asked', async () => {
    renderLayout()
    await userEvent.click(screen.getByRole('tab', { name: 'Timeline' }))
    expect(screen.getByText('timeline-stub')).toBeInTheDocument()
  })

  it('renders the actions passed in, next to the title', () => {
    renderLayout({ actions: <button type="button">Modifica</button> })
    expect(screen.getByRole('button', { name: 'Modifica' })).toBeInTheDocument()
  })

  it('falls back to an honest "no links" message when links are not given', async () => {
    renderLayout({ links: undefined })
    await userEvent.click(screen.getByRole('tab', { name: 'Collegamenti' }))
    expect(screen.getByText('Nessun collegamento.')).toBeInTheDocument()
  })

  it('forwards entityType, entityId and the optional timelineLimit through to Timeline unchanged', async () => {
    renderLayout({ entityType: 'deal', entityId: 'deal-42', timelineLimit: 100 })
    await userEvent.click(screen.getByRole('tab', { name: 'Timeline' }))
    expect(timelineSpy).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({ entityType: 'deal', entityId: 'deal-42', limit: 100 }),
    )
  })

  it('does not require timelineLimit -- Timeline gets its own default', async () => {
    renderLayout()
    await userEvent.click(screen.getByRole('tab', { name: 'Timeline' }))
    expect(timelineSpy).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ limit: undefined }))
  })
})
