import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { List, Plus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { DealForm } from '@/features/deals/DealForm'
import { KanbanBoard } from '@/features/deals/KanbanBoard'
import { useCreateDeal, useDeals, useMoveDeal, useStages } from '@/features/deals/queries'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useCanWrite } from '@/lib/auth'
import { useEntitySchema } from '@/lib/schema'

/** Shown only if `useDeals` ever exhausts its own safety valve (see that hook's
 *  `MAX_PAGES` comment) -- not a state any tenant this product is sized for
 *  should ever reach. Its whole job is to make a truncated board *visible*
 *  instead of a silently wrong column total, so it deliberately reuses the same
 *  destructive-toned banner `DynamicForm`'s own unattributed-error banner uses,
 *  rather than inventing a new "warning" visual language this design system does
 *  not otherwise have. */
function TruncatedNotice({ scope }: { scope: string }) {
  return (
    <p
      role="status"
      className="mb-4 rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
    >
      Ci sono troppi deal da mostrare tutti insieme: alcuni potrebbero mancare {scope}. Contatta un
      amministratore.
    </p>
  )
}

function DealsKanban() {
  const navigate = useNavigate()
  const canWrite = useCanWrite()
  const [open, setOpen] = useState(false)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  const schema = useEntitySchema('deal')
  const stages = useStages()
  // No params: the Kanban's own per-column count and total need *every* deal
  // that exists, not a filtered subset -- see `useDeals`'s own docstring for why
  // it pages through the full result set rather than stopping at the first 50.
  const deals = useDeals()
  const move = useMoveDeal()
  const create = useCreateDeal()

  if (stages.isLoading || deals.isLoading) return <Skeleton className="m-8 h-96" />

  return (
    <div className="p-8">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Deal</h1>
        <div className="flex gap-2">
          <Button variant="outline" asChild>
            <Link to="/app/deal/lista">
              <List className="mr-2 size-4" />
              Vista lista
            </Link>
          </Button>
          {canWrite && (
            <Button
              onClick={() => {
                setProblem(null)
                setOpen(true)
              }}
            >
              <Plus className="mr-2 size-4" />
              Nuovo deal
            </Button>
          )}
        </div>
      </header>

      {deals.data?.truncated && <TruncatedNotice scope="dalla board e dai totali per colonna" />}

      <KanbanBoard
        stages={stages.data ?? []}
        deals={deals.data?.items ?? []}
        canDrag={canWrite}
        onOpen={(dealId) => void navigate({ to: '/app/deal/$dealId', params: { dealId } })}
        onMove={(dealId, stageId) =>
          move.mutate(
            { dealId, stageId },
            {
              // The optimistic move already happened in the cache (see
              // `useMoveDeal`'s own docstring) and, on this same error, has
              // already been rolled back -- this is only the half of "make a
              // failed move visible" this hook cannot do itself: putting the
              // server's own message in front of the user. Verified live: see
              // task-8-report.md for the exact reproduction (a soft-deleted
              // deal's card, dragged from a stale board, 404s with "deal <id>
              // not found" and the toast shows exactly that).
              onError: (error) => toast.error(toProblem(error).detail),
            },
          )
        }
      />

      <DealForm
        title="Nuovo deal"
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
              toast.success('Deal creato')
            },
            onError: (error) => setProblem(toProblem(error)),
          })
        }}
      />
    </div>
  )
}

export const Route = createFileRoute('/app/deal/')({ component: DealsKanban })
