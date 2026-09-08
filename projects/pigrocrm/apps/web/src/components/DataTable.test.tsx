import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { DataTable, type DataTableFeatures } from './DataTable'
import type { ColumnDef } from '@tanstack/react-table'

interface Riga {
  id: string
  nome: string
}

// Two columns on purpose: a plain `accessorKey` (the default "just call
// `getValue()`" cell) and an explicit `cell` render function, so the tests below
// exercise both branches of `table.FlexRender` (v9's replacement for calling
// `flexRender` by hand -- see DataTable.tsx's own comment on why v9's `useTable`
// is used at all here), not only the simpler of the two.
const COLUMNS: ColumnDef<DataTableFeatures, Riga>[] = [
  { accessorKey: 'id', header: 'ID', cell: (info) => `#${info.getValue()}` },
  { accessorKey: 'nome', header: 'Nome' },
]

const ACME: Riga = { id: '1', nome: 'ACME Srl' }
const BETA: Riga = { id: '2', nome: 'Beta SpA' }
const DATA: Riga[] = [ACME, BETA]

function rowFor(text: string): HTMLElement {
  const cell = screen.getByText(text)
  const row = cell.closest('tr')
  if (!row) throw new Error(`no <tr> ancestor for "${text}"`)
  return row
}

describe('DataTable', () => {
  it('renders a header per column and a row per datum, through both a plain accessor and a custom cell', () => {
    render(<DataTable columns={COLUMNS} data={DATA} />)
    expect(screen.getByRole('columnheader', { name: 'ID' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Nome' })).toBeInTheDocument()
    expect(screen.getByText('#1')).toBeInTheDocument()
    expect(screen.getByText('ACME Srl')).toBeInTheDocument()
    expect(screen.getByText('#2')).toBeInTheDocument()
    expect(screen.getByText('Beta SpA')).toBeInTheDocument()
  })

  it('shows a distinguishable loading state instead of the table, not an empty one', () => {
    render(<DataTable columns={COLUMNS} data={[]} isLoading />)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(screen.queryByText('Nessun risultato.')).not.toBeInTheDocument()
  })

  it('shows an honest empty state -- the full table chrome, one row saying so -- once loading is over', () => {
    render(<DataTable columns={COLUMNS} data={[]} />)
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByText('Nessun risultato.')).toBeInTheDocument()
  })

  it('accepts a caller-supplied empty message instead of the default', () => {
    render(<DataTable columns={COLUMNS} data={[]} emptyMessage="Nessun cliente trovato." />)
    expect(screen.getByText('Nessun cliente trovato.')).toBeInTheDocument()
  })

  /**
   * The defect a fix round caught live on Clienti, Persone and Deal alike: a
   * failed list request rendered the exact same "Nessun risultato." row an
   * honestly-empty result gets, with nothing on screen distinguishing "you
   * have none" from "we could not ask". `isError`/`error` exist to make the
   * second claim a visibly different shape, the same way `isLoading` already
   * is -- not a text swap inside the same row.
   */
  it('shows the failed request as a distinct banner, not the same shape an empty result gets', () => {
    const error = { code: 'http_error', detail: 'Il server non risponde.', status: 503 }
    render(<DataTable columns={COLUMNS} data={[]} isError error={error} />)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Il server non risponde.')
    expect(screen.queryByText('Nessun risultato.')).not.toBeInTheDocument()
  })

  it('uses the server’s own message in the failed-request banner, not a client-side rewording', () => {
    const error = { code: 'not_found', detail: 'cliente 123 non trovato' }
    render(<DataTable columns={COLUMNS} data={[]} isError error={error} />)
    expect(screen.getByRole('alert')).toHaveTextContent('cliente 123 non trovato')
  })

  /**
   * A background refetch can fail while a previous, successful page is still
   * cached (`data` non-empty even though `isError` is true) -- this must keep
   * showing that stale-but-real data, not discard it for a banner over one
   * transient blip. Only the "nothing else to show" case (the test above)
   * should replace the table at all.
   */
  it('keeps showing already-loaded rows instead of a banner when a background refetch fails', () => {
    render(
      <DataTable
        columns={COLUMNS}
        data={DATA}
        isError
        error={{ code: 'http_error', detail: 'Aggiornamento fallito.' }}
      />,
    )
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByText('ACME Srl')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('calls onRowClick with the original row datum, not a table-internal wrapper', async () => {
    const onRowClick = vi.fn()
    render(<DataTable columns={COLUMNS} data={DATA} onRowClick={onRowClick} />)
    await userEvent.click(screen.getByText('ACME Srl'))
    expect(onRowClick).toHaveBeenCalledExactlyOnceWith(ACME)
  })

  it('leaves rows out of tab order when no onRowClick is given -- nothing to activate', () => {
    render(<DataTable columns={COLUMNS} data={DATA} />)
    expect(rowFor('ACME Srl')).not.toHaveAttribute('tabindex')
  })

  it('puts a clickable row in tab order', () => {
    render(<DataTable columns={COLUMNS} data={DATA} onRowClick={vi.fn()} />)
    expect(rowFor('ACME Srl')).toHaveAttribute('tabindex', '0')
  })

  it('activates a row from the keyboard with Enter, mirroring a click', () => {
    const onRowClick = vi.fn()
    render(<DataTable columns={COLUMNS} data={DATA} onRowClick={onRowClick} />)
    fireEvent.keyDown(rowFor('Beta SpA'), { key: 'Enter' })
    expect(onRowClick).toHaveBeenCalledExactlyOnceWith(BETA)
  })

  it('activates a row from the keyboard with Space too', () => {
    const onRowClick = vi.fn()
    render(<DataTable columns={COLUMNS} data={DATA} onRowClick={onRowClick} />)
    fireEvent.keyDown(rowFor('Beta SpA'), { key: ' ' })
    expect(onRowClick).toHaveBeenCalledExactlyOnceWith(BETA)
  })

  it('ignores a key that is neither Enter nor Space', () => {
    const onRowClick = vi.fn()
    render(<DataTable columns={COLUMNS} data={DATA} onRowClick={onRowClick} />)
    fireEvent.keyDown(rowFor('Beta SpA'), { key: 'a' })
    expect(onRowClick).not.toHaveBeenCalled()
  })
})
