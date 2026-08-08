import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Plus, Search } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { DataTable } from '@/components/DataTable'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { buildPersonColumns } from '@/features/people/columns'
import { PersonForm } from '@/features/people/PersonForm'
import { useCreatePerson, usePeople } from '@/features/people/queries'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useCanWrite } from '@/lib/auth'
import { useEntitySchema } from '@/lib/schema'

function PeoplePage() {
  const navigate = useNavigate()
  const canWrite = useCanWrite()
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(false)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  const schema = useEntitySchema('person')
  const people = usePeople({ search: search || undefined })
  const create = useCreatePerson()

  // Recomputed every render, not memoised -- same call as `CustomersPage`'s
  // identical line: `schema.data?.custom_fields` only changes when the schema
  // query itself refetches, and building a handful of plain objects is not
  // worth a `useMemo` whose dependency array would just repeat the query result.
  const columns = buildPersonColumns(schema.data?.custom_fields ?? [])

  return (
    <div className="p-8">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Persone</h1>
        {canWrite && (
          <Button
            onClick={() => {
              setProblem(null)
              setOpen(true)
            }}
          >
            <Plus className="mr-2 size-4" />
            Nuova persona
          </Button>
        )}
      </header>

      <div className="relative mb-4 max-w-sm">
        <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          className="pl-9"
          placeholder="Cerca per nome, cognome o email…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      <DataTable
        columns={columns}
        data={people.data?.items ?? []}
        isLoading={people.isLoading}
        onRowClick={(row) =>
          void navigate({ to: '/app/persone/$personId', params: { personId: row.id } })
        }
        emptyMessage="Nessuna persona. Creane una per iniziare."
      />

      <PersonForm
        title="Nuova persona"
        open={open}
        onOpenChange={setOpen}
        customFields={schema.data?.custom_fields ?? []}
        problem={problem}
        busy={create.isPending}
        onSubmit={(values) => {
          setProblem(null)
          create.mutate(values, {
            onSuccess: () => {
              setOpen(false)
              toast.success('Persona creata')
            },
            onError: (error) => setProblem(toProblem(error)),
          })
        }}
      />
    </div>
  )
}

export const Route = createFileRoute('/app/persone/')({ component: PeoplePage })
