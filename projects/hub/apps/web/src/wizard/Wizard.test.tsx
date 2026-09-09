import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Wizard, type Step } from './Wizard'

interface Form {
  nome: string
  email: string
}

const STEPS: Step<Form>[] = [
  {
    id: 'nome',
    title: 'Come ti chiami?',
    render: ({ value, set }) => (
      <input aria-label="Nome" value={value.nome} onChange={(e) => set({ nome: e.target.value })} />
    ),
    validate: (v) => (v.nome.trim() ? null : 'Serve un nome.'),
    summary: (v) => v.nome,
  },
  {
    id: 'email',
    title: 'La tua email?',
    render: ({ value, set }) => (
      <input aria-label="Email" value={value.email} onChange={(e) => set({ email: e.target.value })} />
    ),
    validate: (v) => (v.email.includes('@') ? null : 'Serve una email.'),
    summary: (v) => v.email,
  },
]

function Harness({
  onSubmit,
  submitError = null,
}: {
  onSubmit: () => void
  submitError?: { message: string; step?: string } | null
}) {
  const [value, setValue] = useState<Form>({ nome: '', email: '' })
  return (
    <Wizard
      title="Test"
      steps={STEPS}
      value={value}
      set={(patch) => setValue((v) => ({ ...v, ...patch }))}
      onSubmit={onSubmit}
      submitting={false}
      submitError={submitError}
      submitLabel="Invia"
    />
  )
}

describe('Wizard', () => {
  it('asks one question at a time, refuses to go on with an empty answer, reviews, submits', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<Harness onSubmit={onSubmit} />)

    expect(screen.getByRole('heading', { name: 'Come ti chiami?' })).toBeInTheDocument()
    expect(screen.getByText('1 di 2')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Avanti/ }))
    expect(screen.getByRole('alert')).toHaveTextContent('Serve un nome.')

    await user.type(screen.getByLabelText('Nome'), 'Ada{Enter}')
    expect(screen.getByRole('heading', { name: 'La tua email?' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    await user.type(screen.getByLabelText('Email'), 'ada@studio.it{Enter}')
    expect(screen.getByRole('heading', { name: 'Tutto giusto?' })).toBeInTheDocument()
    expect(screen.getByText('ada@studio.it')).toBeInTheDocument()

    await user.click(screen.getAllByRole('button', { name: 'Modifica' })[0]!)
    expect(screen.getByLabelText('Nome')).toHaveValue('Ada')
    await user.click(screen.getByRole('button', { name: /Avanti/ }))
    await user.click(screen.getByRole('button', { name: /Rivedi/ }))

    await user.click(screen.getByRole('button', { name: /Invia/ }))
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('goes back to the step a server error names', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<Harness onSubmit={() => {}} />)
    await user.type(screen.getByLabelText('Nome'), 'Ada{Enter}')
    await user.type(screen.getByLabelText('Email'), 'ada@studio.it{Enter}')
    expect(screen.getByRole('heading', { name: 'Tutto giusto?' })).toBeInTheDocument()

    rerender(
      <Harness onSubmit={() => {}} submitError={{ message: 'Email già usata.', step: 'email' }} />,
    )
    expect(screen.getByRole('heading', { name: 'La tua email?' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Email già usata.')
  })
})
