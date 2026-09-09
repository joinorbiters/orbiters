import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Plus, Search, Users } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { DataTable } from '@/components/DataTable'
import { FilterRow } from '@/components/FilterRow'
import { PageHeader } from '@/components/PageHeader'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useCustomers } from '@/features/customers/queries'
import { buildPersonColumns } from '@/features/people/columns'
import { PersonForm } from '@/features/people/PersonForm'
import { useCreatePerson, usePeople } from '@/features/people/queries'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useCanWrite } from '@/lib/auth'
import { useEntitySchema } from '@/lib/schema'

/** `tutte` is a UI-only value, the same idiom `fatture/index.tsx`'s `ANY` uses for its
 *  type select: the API filter is simply absent when nothing is chosen, and a `Select`
 *  needs a non-empty string to represent "no filter". A customer id is always a UUID
 *  minted by the database, so no real id can ever collide with this literal. */
const ALL_COMPANIES = 'tutte'

/**
 * Exported so `index.test.tsx` can render the list without a router -- the same split
 * `CustomersPage` makes next door.
 *
 * `customerId` is a controlled prop, not local state: unlike the search box, the
 * «Azienda» select has to navigate (see the `Select` below), because `customer_id` is
 * a real server-side filter (`GET /api/people?customer_id=`) and the URL is what
 * survives a bookmark, a reload or the `key`-driven remount `PeopleRoute` does for
 * `search`.
 */
export function PeoplePage({
  initialSearch,
  customerId,
}: {
  initialSearch: string
  customerId?: string
}) {
  const navigate = useNavigate()
  const canWrite = useCanWrite()
  const [search, setSearch] = useState(initialSearch)
  const [open, setOpen] = useState(false)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  const schema = useEntitySchema('person')
  const people = usePeople({ search: search || undefined, customer_id: customerId })
  const create = useCreatePerson()

  // `limit: 200` mirrors `PersonForm`'s own `CustomerPicker` -- a one-shot cap for a
  // dropdown, not this screen's own list.
  const customers = useCustomers({ limit: 200 })

  // Sorted here, client-side, rather than asked of the API: `useCustomers` has no
  // `sort` parameter of its own (its default order is `created_at`, see
  // `CustomersListParams`), and this dropdown is a handful of rows, not a page that
  // needs the server's keyset pagination to sort correctly.
  const sortedCustomers = useMemo(
    () =>
      [...(customers.data?.items ?? [])].sort((a, b) =>
        a.ragione_sociale.localeCompare(b.ragione_sociale, 'it'),
      ),
    [customers.data],
  )

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
      >
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

          {/* Navigates rather than filtering locally, the same reasoning
              `deal/lista.tsx`'s chips carry for their own server-evaluated filter:
              `customer_id` is a real `GET /api/people` query parameter, and `search` is
              an *updater*, not a literal object, so the box's own `?search=` term
              survives a company chosen here. */}
          <Select
            value={customerId ?? ALL_COMPANIES}
            onValueChange={(next) =>
              void navigate({
                to: '/app/persone',
                search: (previous) => ({
                  search: previous.search,
                  customer_id: next === ALL_COMPANIES ? undefined : next,
                }),
              })
            }
          >
            <SelectTrigger className="w-56" aria-label="Filtra per azienda">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_COMPANIES}>Tutte le aziende</SelectItem>
              {sortedCustomers.map((customer) => (
                <SelectItem key={customer.id} value={customer.id}>
                  {customer.ragione_sociale}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FilterRow>
      </PageHeader>

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
 *
 * `customer_id` is not part of that `key`: unlike `search`, the «Azienda» select is a
 * controlled prop of `PeoplePage` (see its own docstring), so a change to it re-renders
 * the page instead of remounting it.
 */
function PeopleRoute() {
  const { search, customer_id } = Route.useSearch()
  return <PeoplePage key={search ?? ''} initialSearch={search ?? ''} customerId={customer_id} />
}

export const Route = createFileRoute('/app/persone/')({
  component: PeopleRoute,
  // Declared so the palette can link here with a term (`navigate({ to, search })` is
  // typed against this). An empty or non-string value is dropped rather than carried as
  // `?search=`/`?customer_id=`, so the URL never claims a filter that is not applied.
  validateSearch: (
    search: Record<string, unknown>,
  ): { search?: string; customer_id?: string } => ({
    search:
      typeof search.search === 'string' && search.search.length > 0 ? search.search : undefined,
    customer_id:
      typeof search.customer_id === 'string' && search.customer_id.length > 0
        ? search.customer_id
        : undefined,
  }),
})
