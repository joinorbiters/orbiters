import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { LayoutGrid, Search } from 'lucide-react'
import { useState } from 'react'
import { DataTable } from '@/components/DataTable'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { buildDealColumns } from '@/features/deals/columns'
import { useDeals } from '@/features/deals/queries'
import { useEntitySchema } from '@/lib/schema'

function DealsList({ initialSearch }: { initialSearch: string }) {
  const navigate = useNavigate()
  const [search, setSearch] = useState(initialSearch)
  const schema = useEntitySchema('deal')
  const deals = useDeals({ search: search || undefined })

  // Recomputed every render, not memoised -- same call as `CustomersPage`/
  // `PeoplePage`'s identical line: not worth a `useMemo` whose dependency array
  // would just repeat the schema query's own result.
  const columns = buildDealColumns(schema.data?.custom_fields ?? [])

  return (
    <div className="p-8">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Deal — lista</h1>
        <Button variant="outline" asChild>
          <Link to="/app/deal">
            <LayoutGrid className="mr-2 size-4" />
            Vista Kanban
          </Link>
        </Button>
      </header>

      <div className="relative mb-4 max-w-sm">
        <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          className="pl-9"
          placeholder="Cerca per nome…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      {deals.data?.truncated && (
        <p
          role="status"
          className="mb-4 rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          Ci sono troppi deal da mostrare tutti insieme: alcuni potrebbero mancare da questo
          elenco. Contatta un amministratore.
        </p>
      )}

      <DataTable
        columns={columns}
        data={deals.data?.items ?? []}
        isLoading={deals.isLoading}
        isError={deals.isError}
        error={deals.error}
        onRowClick={(row) => void navigate({ to: '/app/deal/$dealId', params: { dealId: row.id } })}
        emptyMessage="Nessun deal."
      />
    </div>
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
function DealsListRoute() {
  const { search } = Route.useSearch()
  return <DealsList key={search ?? ''} initialSearch={search ?? ''} />
}

export const Route = createFileRoute('/app/deal/lista')({
  component: DealsListRoute,
  // Declared so the palette can link here with a term (`navigate({ to, search })` is
  // typed against this). An empty or non-string value is dropped rather than carried as
  // `?search=`, so the URL never claims a filter that is not applied.
  validateSearch: (search: Record<string, unknown>): { search?: string } => ({
    search:
      typeof search.search === 'string' && search.search.length > 0 ? search.search : undefined,
  }),
})
