import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { LayoutGrid, Search } from 'lucide-react'
import { useState } from 'react'
import { DataTable } from '@/components/DataTable'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { buildDealColumns } from '@/features/deals/columns'
import { useDeals, type DealsListParams } from '@/features/deals/queries'
import { useEntitySchema } from '@/lib/schema'
import { booleanSearchParam } from '@/lib/searchParams'

/**
 * The two dashboard drill-throughs, and the sentence each of them puts on screen.
 *
 * Named here rather than inferred from the URL at the point of use so that a filter can
 * never be applied without also being *stated*: a list silently shorter than the one the
 * user asked for is the failure this whole slice calls a partial result. Criterion 2 is
 * the other half -- these are the same predicates the operational dashboard's counts are
 * built from, evaluated by the same code in `packages/core`, which is why they travel to
 * the server rather than being reimplemented over the fetched page.
 */
const DRILL_THROUGHS = [
  {
    key: 'fatturato_non_vinto',
    label: 'Fatturato ma non vinto',
    explanation:
      'Solo i deal con almeno una fattura emessa che non risultano vinti. Togli il filtro per vedere tutti i deal.',
  },
  {
    key: 'da_fatturare',
    label: 'Vinto ma da fatturare',
    explanation:
      'Solo i deal vinti con ore fatturabili non ancora fatturate. Togli il filtro per vedere tutti i deal.',
  },
] as const

function DealsList({
  initialSearch,
  filters,
}: {
  initialSearch: string
  filters: Pick<DealsListParams, 'fatturato_non_vinto' | 'da_fatturare'>
}) {
  const navigate = useNavigate()
  const [search, setSearch] = useState(initialSearch)
  const schema = useEntitySchema('deal')
  const deals = useDeals({ search: search || undefined, ...filters })
  const active = DRILL_THROUGHS.filter((candidate) => filters[candidate.key] === true)

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

      {active.length > 0 && (
        <div className="mb-4 space-y-2">
          {active.map((filter) => (
            <p
              key={filter.key}
              role="status"
              className="flex flex-wrap items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm"
            >
              <span>
                <strong>{filter.label}</strong> — {filter.explanation}
              </span>
              <Button variant="outline" size="sm" asChild>
                <Link to="/app/deal/lista" search={{}}>
                  Rimuovi il filtro
                </Link>
              </Button>
            </p>
          ))}
        </div>
      )}

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
  const { search, fatturato_non_vinto, da_fatturare } = Route.useSearch()
  return (
    <DealsList
      key={search ?? ''}
      initialSearch={search ?? ''}
      filters={{ fatturato_non_vinto, da_fatturare }}
    />
  )
}

export const Route = createFileRoute('/app/deal/lista')({
  component: DealsListRoute,
  // Declared so the palette can link here with a term, and so the operational dashboard
  // can link here with a drill-through (`<Link to={...} search={...} />` is typed against
  // this function's *return* type, not its parameter type). An empty or non-string value
  // is dropped rather than carried as `?search=`, so the URL never claims a filter that is
  // not applied -- and the two booleans are carried only when they are literally `true`,
  // so `?da_fatturare=false` is the absence of a filter rather than a third state.
  validateSearch: (
    search: Record<string, unknown>,
  ): { search?: string; fatturato_non_vinto?: boolean; da_fatturare?: boolean } => ({
    search:
      typeof search.search === 'string' && search.search.length > 0 ? search.search : undefined,
    fatturato_non_vinto: booleanSearchParam(search.fatturato_non_vinto),
    da_fatturare: booleanSearchParam(search.da_fatturare),
  }),
})
