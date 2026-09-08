import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatusPill } from './StatusPill'

function dotOf(container: HTMLElement): HTMLElement {
  const dot = container.querySelector('[data-slot="badge-dot"]')
  if (!(dot instanceof HTMLElement)) throw new Error('la pillola non ha il punto colorato')
  return dot
}

describe('StatusPill', () => {
  it('renders the Italian label it is given, unchanged', () => {
    render(<StatusPill tone="ink">Emessa</StatusPill>)
    expect(screen.getByText('Emessa')).toBeInTheDocument()
  })

  it('carries the coloured dot the reference screenshots put before the label', () => {
    const { container } = render(<StatusPill tone="gold">Da incassare</StatusPill>)
    expect(dotOf(container)).toBeInTheDocument()
  })

  /** The label says the state in words, so a reader who cannot separate two hues has
   *  lost nothing -- and a screen reader must not announce the dot twice. */
  it('hides the dot from assistive technology, because the label already says it', () => {
    const { container } = render(<StatusPill tone="danger">Annullata</StatusPill>)
    expect(dotOf(container)).toHaveAttribute('aria-hidden', 'true')
  })

  it('tints the dot per tone rather than always the same colour', () => {
    const ink = render(<StatusPill tone="ink">Emessa</StatusPill>)
    const danger = render(<StatusPill tone="danger">Annullata</StatusPill>)
    expect(dotOf(ink.container).className).not.toBe(dotOf(danger.container).className)
  })

  it('is the soft pill badge, not the filled default one', () => {
    render(<StatusPill tone="muted">Bozza</StatusPill>)
    expect(screen.getByText('Bozza').closest('[data-slot="badge"]')).toHaveAttribute(
      'data-variant',
      'pill',
    )
  })

  it('names its own tone in the DOM, so a table row can be inspected without reading classes', () => {
    render(<StatusPill tone="accent">Consumata</StatusPill>)
    expect(screen.getByText('Consumata').closest('[data-slot="badge"]')).toHaveAttribute(
      'data-tone',
      'accent',
    )
  })
})
