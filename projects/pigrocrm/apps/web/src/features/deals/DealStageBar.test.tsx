import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { DealStageBar } from './DealStageBar'
import type { Deal, Stage } from './queries'

const STAGES: Stage[] = [
  { id: 's3', nome: 'Proposta', posizione: 3, probabilita_default: 60, tipo: 'open', code: null },
  { id: 's1', nome: 'Contatto', posizione: 1, probabilita_default: 10, tipo: 'open', code: null },
  { id: 's2', nome: 'Analisi', posizione: 2, probabilita_default: 30, tipo: 'open', code: null },
  { id: 'won', nome: 'Vinto', posizione: 4, probabilita_default: 100, tipo: 'won', code: 'won' },
  { id: 'lost', nome: 'Perso', posizione: 5, probabilita_default: 0, tipo: 'lost', code: 'lost' },
]

function deal(stageId: string): Deal {
  return { id: 'd1', nome: 'Sito', pipeline_stage_id: stageId } as unknown as Deal
}

describe('DealStageBar', () => {
  it('draws the open stages in pipeline order and marks the current one', () => {
    render(<DealStageBar deal={deal('s2')} stages={STAGES} canMove onMove={vi.fn()} />)
    const segments = screen.getAllByRole('button')
    // Ordered by `posizione`, not by the order the API happened to return them in, and
    // the two outcomes are not steps.
    expect(segments.map((button) => button.textContent)).toEqual(['Contatto', 'Analisi', 'Proposta'])
    expect(screen.getByRole('button', { name: 'Analisi' })).toHaveAttribute('aria-current', 'step')
    expect(screen.getByText(/Fase attuale/)).toHaveTextContent('Analisi')
  })

  it('moves the deal to the stage that was pressed, and never to the one it is in', async () => {
    const onMove = vi.fn()
    render(<DealStageBar deal={deal('s1')} stages={STAGES} canMove onMove={onMove} />)
    await userEvent.click(screen.getByRole('button', { name: 'Proposta' }))
    expect(onMove).toHaveBeenCalledWith('s3')
    expect(screen.getByRole('button', { name: 'Contatto' })).toBeDisabled()
  })

  it('offers nothing to press to a reader without write access', () => {
    render(<DealStageBar deal={deal('s1')} stages={STAGES} canMove={false} onMove={vi.fn()} />)
    for (const button of screen.getAllByRole('button')) expect(button).toBeDisabled()
    expect(screen.queryByText(/Clicca una fase/)).toBeNull()
  })

  it('says how a closed deal ended and how to reopen it', () => {
    render(<DealStageBar deal={deal('lost')} stages={STAGES} canMove onMove={vi.fn()} />)
    expect(screen.getByText('Perso')).toBeInTheDocument()
    expect(screen.getByText(/Per riaprirlo/)).toBeInTheDocument()
    // Every segment is pressable again: reopening is a move like any other.
    for (const button of screen.getAllByRole('button')) expect(button).toBeEnabled()
  })
})
