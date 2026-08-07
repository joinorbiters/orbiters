import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { DynamicForm } from './DynamicForm'
import type { ProblemDetail } from '@/lib/api'
import type { FieldDefinition } from '@/lib/schema'

const FIELDS: FieldDefinition[] = [
  { key: 'partita_iva', label: 'Partita IVA', type: 'text', required: false, options: [] },
  { key: 'note_interne', label: 'Note interne', type: 'textarea', required: false, options: [] },
]

// The real shape `domain_error_handler` renders for a validation failure (see
// lib/api.test.ts's PROBLEM) -- the one case where `fieldErrorFrom` has something
// to attach.
const VALIDATION_PROBLEM: ProblemDetail = {
  type: 'https://pigrocrm.dev/errors/validation_failed',
  title: 'Dati non validi',
  status: 422,
  detail: 'customer.partita_iva: deve essere di 11 cifre',
  code: 'validation_failed',
  entity: 'customer',
  field: 'partita_iva',
  reason: 'deve essere di 11 cifre',
  expected: '11 cifre numeriche',
}

describe('DynamicForm', () => {
  it('renders a control for every field, addressable by its label', () => {
    render(<DynamicForm fields={FIELDS} values={{}} onChange={vi.fn()} />)
    expect(screen.getByLabelText('Partita IVA')).toBeInTheDocument()
    expect(screen.getByLabelText('Note interne')).toBeInTheDocument()
  })

  it('reports an edit with the key of the field that changed, not just the value', async () => {
    const onChange = vi.fn()
    render(<DynamicForm fields={FIELDS} values={{}} onChange={onChange} />)
    await userEvent.type(screen.getByLabelText('Partita IVA'), 'x')
    expect(onChange).toHaveBeenCalledWith('partita_iva', 'x')
  })

  it('reads each field from its own key in values, defaulting an absent one to null', () => {
    render(
      <DynamicForm fields={FIELDS} values={{ partita_iva: '01234567890' }} onChange={vi.fn()} />,
    )
    expect(screen.getByLabelText('Partita IVA')).toHaveValue('01234567890')
    expect(screen.getByLabelText('Note interne')).toHaveValue('')
  })

  it('attaches the server error to the one field it names, and no other', () => {
    render(
      <DynamicForm fields={FIELDS} values={{}} onChange={vi.fn()} problem={VALIDATION_PROBLEM} />,
    )
    expect(
      screen.getByText('deve essere di 11 cifre (atteso: 11 cifre numeriche)'),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Partita IVA')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText('Note interne')).toHaveAttribute('aria-invalid', 'false')
  })

  it('marks nothing invalid when there is no problem at all', () => {
    render(<DynamicForm fields={FIELDS} values={{}} onChange={vi.fn()} problem={null} />)
    expect(screen.getByLabelText('Partita IVA')).toHaveAttribute('aria-invalid', 'false')
    expect(screen.getByLabelText('Note interne')).toHaveAttribute('aria-invalid', 'false')
  })

  it('marks nothing invalid when the problem names a field this form does not have', () => {
    render(
      <DynamicForm
        fields={FIELDS}
        values={{}}
        onChange={vi.fn()}
        problem={{ ...VALIDATION_PROBLEM, field: 'qualcos_altro' }}
      />,
    )
    expect(screen.getByLabelText('Partita IVA')).toHaveAttribute('aria-invalid', 'false')
    expect(screen.getByLabelText('Note interne')).toHaveAttribute('aria-invalid', 'false')
  })

  it('does not treat a non-validation problem (e.g. a conflict) as belonging to any field', () => {
    render(
      <DynamicForm
        fields={FIELDS}
        values={{}}
        onChange={vi.fn()}
        problem={{ ...VALIDATION_PROBLEM, code: 'conflict', field: 'partita_iva' }}
      />,
    )
    expect(screen.getByLabelText('Partita IVA')).toHaveAttribute('aria-invalid', 'false')
  })
})
