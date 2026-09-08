import { render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { sollecitiColumns } from './columns'
import type { SollecitoCandidate } from './queries'

const CANDIDATE: SollecitoCandidate = {
  invoice_id: 'i1',
  numero: '2026/7',
  data_fattura: '2026-01-15',
  data_scadenza: '2026-02-14',
  giorni_di_ritardo: 42,
  importo: '2500.50',
  cliente: 'ACME Srl',
  customer_id: 'c1',
  solleciti_inviati: 1,
  ultimo_sollecito_il: '2026-03-05',
  prossimo_livello: 2,
  ultima_risposta_il: null,
}

function columns() {
  return sollecitiColumns(vi.fn(), null)
}

/**
 * Reads a column's rendered cell, not only its accessor -- the accessor keeps the plain
 * text value, `cell` carries what the design revision adds (design spec §4). Only
 * `row.original` is consulted, so the cast supplies exactly that.
 */
function renderCell(id: string, candidate: SollecitoCandidate) {
  const column = columns().find((candidate_) => candidate_.id === id)
  if (column === undefined || typeof column.cell !== 'function') {
    throw new Error(`la colonna ${id} non ha un cell renderer`)
  }
  return render(column.cell({ row: { original: candidate } } as never) as ReactElement)
}

function column(id: string) {
  const found = columns().find((candidate) => candidate.id === id)
  if (found === undefined) throw new Error(`nessuna colonna con id ${id}`)
  return found
}

describe('how a candidate for a reminder reads', () => {
  /** This table is read by scanning down the two numeric columns for the worst row, so
   *  the headers have to sit over the digits they label. */
  it('declares the days late and the amount right-aligned columns', () => {
    expect(column('giorni_di_ritardo').meta).toEqual({ align: 'right' })
    expect(column('importo').meta).toEqual({ align: 'right' })
  })

  it('aligns the amount on tabular digits', () => {
    renderCell('importo', CANDIDATE)
    expect(screen.getByText(/2\.500,50/).className).toContain('text-right')
  })

  it('aligns the day count too, through the number cell rather than the money one', () => {
    renderCell('giorni_di_ritardo', CANDIDATE)
    const cell = screen.getByText('42')
    expect(cell.className).toContain('text-right')
    expect(cell.className).toContain('tabular-nums')
  })

  it('puts a calendar icon before the date of the last reminder', () => {
    const { container } = renderCell('ultimo_sollecito_il', CANDIDATE)
    expect(screen.getByText('05/03/2026')).toBeInTheDocument()
    expect(container.querySelector('svg')).not.toBeNull()
  })

  it('shows an invoice never chased as the dash, with no calendar claiming a date', () => {
    const { container } = renderCell('ultimo_sollecito_il', {
      ...CANDIDATE,
      ultimo_sollecito_il: null,
    })
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(container.querySelector('svg')).toBeNull()
  })
})

/**
 * Controller ruling, recorded here so a later "consistency" pass does not quietly undo
 * it: «Prepara sollecito» stays a plain button in the row and does *not* move into the
 * «⋯» menu. It is the only reason this screen exists -- every column before it answers a
 * question somebody would otherwise answer by hand, and the last one is the button.
 */
describe('the action that chases the money', () => {
  it('stays a button in the row, not an item hidden behind a menu', () => {
    const onPrepare = vi.fn()
    const azione = sollecitiColumns(onPrepare, null).find((candidate) => candidate.id === 'azione')
    if (azione === undefined || typeof azione.cell !== 'function') {
      throw new Error('la colonna azione non ha un cell renderer')
    }
    render(azione.cell({ row: { original: CANDIDATE } } as never) as ReactElement)
    expect(screen.getByRole('button', { name: 'Prepara sollecito' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Azioni' })).not.toBeInTheDocument()
  })

  it('disables the button of the row whose reminder is being prepared', () => {
    const azione = sollecitiColumns(vi.fn(), 'i1').find((candidate) => candidate.id === 'azione')
    if (azione === undefined || typeof azione.cell !== 'function') {
      throw new Error('la colonna azione non ha un cell renderer')
    }
    render(azione.cell({ row: { original: CANDIDATE } } as never) as ReactElement)
    expect(screen.getByRole('button', { name: 'Prepara sollecito' })).toBeDisabled()
  })
})
