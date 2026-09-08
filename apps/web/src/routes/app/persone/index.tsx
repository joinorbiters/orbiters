import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Plus, Search, Users } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { DataTable } from '@/components/DataTable'
import { FilterRow } from '@/components/FilterRow'
import { PageHeader } from '@/components/PageHeader'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { buildPersonColumns } from '@/features/people/columns'
import { PersonForm } from '@/features/people/PersonForm'
import { useCreatePerson, usePeople } from '@/features/people/queries'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useCanWrite } from '@/lib/auth'
import { useEntitySchema } from '@/lib/schema'

/**
 * Exported so `index.test.tsx` can render the list without a router -- the same split
 * `CustomersPage` makes next door.
 */
export function PeoplePage({ initialSearch }: { initialSearch: string }) {
  const navigate = useNavigate()
  const canWrite = useCanWrite()
  const [search, setSearch] = useState(initialSearch)
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
    <>
      <PageHeader
        icon={Users}
        title="Persone"
        actions={
          canWrite && (
            <Button
              onClick={() => {
                setProblem(null)
                setOpen(true)
              }}
            >
              <Plus className="mr-2 size-4" />
              Nuova persona
            </Button>
          )
        }
      />

      {/* Search only, like Clienti: a person has no state, and this revision adds no
          filter a page did not already have. */}
      <FilterRow>
        <div className="relative w-full max-w-sm">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-9"
            placeholder="Cerca per nome, cognome o email…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
      </FilterRow>

      <div className="px-8 pb-8">
        <DataTable
          columns={columns}
          data={people.data?.items ?? []}
          isLoading={people.isLoading}
          isError={people.isError}
          error={people.error}
          onRowClick={(row) =>
            void navigate({ to: '/app/persone/$personId', params: { personId: row.id } })
          }
          emptyMessage="Nessuna persona. Creane una per iniziare."
        />
      </div>

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
    </>
  )
}

/**
 * The `?search=` term is an entry point, not a live mirror of the box. The palette's
 * «vedi tutti» links here carrying the term the user searched for, and `key` makes
 * arriving with a *different* term a remount, so the filter is seeded even when this
 * route is already open. Typing afterwards stays local: pushing every keystroke through
 * the router would make a controlled input wait on a navigation to echo the character
 * back, which is how a fast typist loses characters.
 */
function PeopleRoute() {
  const { search } = Route.useSearch()
  return <PeoplePage key={search ?? ''} initialSearch={search ?? ''} />
}

export const Route = createFileRoute('/app/persone/')({
  component: PeopleRoute,
  // Declared so the palette can link here with a term (`navigate({ to, search })` is
  // typed against this). An empty or non-string value is dropped rather than carried as
  // `?search=`, so the URL never claims a filter that is not applied.
  validateSearch: (search: Record<string, unknown>): { search?: string } => ({
    search:
      typeof search.search === 'string' && search.search.length > 0 ? search.search : undefined,
  }),
})
