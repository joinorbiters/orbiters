import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { DynamicFieldRenderer, renderFieldValue } from './DynamicFieldRenderer'
import type { FieldDefinition } from '@/lib/schema'

const field = (over: Partial<FieldDefinition>): FieldDefinition => ({
  key: 'campo',
  label: 'Campo',
  type: 'text',
  required: false,
  options: [],
  ...over,
})

describe('DynamicFieldRenderer', () => {
  it('renders a text input with its label', () => {
    render(<DynamicFieldRenderer field={field({})} value={null} onChange={vi.fn()} />)
    expect(screen.getByLabelText('Campo')).toBeInTheDocument()
  })

  it('marks a required field', () => {
    render(<DynamicFieldRenderer field={field({ required: true })} value={null} onChange={vi.fn()} />)
    expect(screen.getByText('*')).toBeInTheDocument()
  })

  it('renders a textarea for textarea fields', () => {
    render(<DynamicFieldRenderer field={field({ type: 'textarea' })} value={null} onChange={vi.fn()} />)
    expect(screen.getByLabelText('Campo').tagName).toBe('TEXTAREA')
  })

  it('renders a numeric input for number fields', () => {
    render(<DynamicFieldRenderer field={field({ type: 'number' })} value={null} onChange={vi.fn()} />)
    expect(screen.getByLabelText('Campo')).toHaveAttribute('type', 'number')
  })

  it('renders a checkbox for checkbox fields', () => {
    render(<DynamicFieldRenderer field={field({ type: 'checkbox' })} value={false} onChange={vi.fn()} />)
    expect(screen.getByRole('checkbox')).toBeInTheDocument()
  })

  it('renders a date input for date fields', () => {
    render(<DynamicFieldRenderer field={field({ type: 'date' })} value={null} onChange={vi.fn()} />)
    expect(screen.getByLabelText('Campo')).toHaveAttribute('type', 'date')
  })

  it('offers every declared option for a select', async () => {
    render(
      <DynamicFieldRenderer
        field={field({ type: 'select', options: ['attivo', 'sospeso'] })}
        value={null}
        onChange={vi.fn()}
      />,
    )
    await userEvent.click(screen.getByRole('combobox'))
    expect(screen.getByText('attivo')).toBeInTheDocument()
    expect(screen.getByText('sospeso')).toBeInTheDocument()
  })

  it('reports edits through onChange', async () => {
    const onChange = vi.fn()
    render(<DynamicFieldRenderer field={field({})} value={null} onChange={onChange} />)
    await userEvent.type(screen.getByLabelText('Campo'), 'x')
    expect(onChange).toHaveBeenCalledWith('x')
  })

  it('shows the server-side error next to the input', () => {
    render(
      <DynamicFieldRenderer field={field({})} value={null} onChange={vi.fn()} error="deve essere di 11 cifre" />,
    )
    expect(screen.getByText('deve essere di 11 cifre')).toBeInTheDocument()
  })
})

describe('renderFieldValue', () => {
  it('shows an em dash for an empty value', () => {
    expect(renderFieldValue(field({}), null)).toBe('—')
  })

  it('formats currency in euros', () => {
    expect(renderFieldValue(field({ type: 'currency' }), '1234.56')).toContain('1.234,56')
  })

  it('formats dates in the Italian order', () => {
    expect(renderFieldValue(field({ type: 'date' }), '2026-08-06')).toBe('06/08/2026')
  })

  it('renders booleans as Sì / No', () => {
    expect(renderFieldValue(field({ type: 'checkbox' }), true)).toBe('Sì')
    expect(renderFieldValue(field({ type: 'checkbox' }), false)).toBe('No')
  })

  it('joins multiselect values', () => {
    expect(renderFieldValue(field({ type: 'multiselect' }), ['a', 'b'])).toBe('a, b')
  })
})
