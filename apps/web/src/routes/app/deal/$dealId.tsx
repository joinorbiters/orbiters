import { createFileRoute, useNavigate, useParams } from '@tanstack/react-router'
import { Pencil, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { renderFieldValue } from '@/components/DynamicFieldRenderer'
import { EntityDetailLayout } from '@/components/EntityDetailLayout'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useCustomer } from '@/features/customers/queries'
import { DealForm, dealToFormValues } from '@/features/deals/DealForm'
import { displayNative, formatDate, formatHours, formatMoney } from '@/features/deals/columns'
import { useDeal, useDeleteDeal, useStages, useUpdateDeal } from '@/features/deals/queries'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useCanWrite } from '@/lib/auth'
import { useEntitySchema } from '@/lib/schema'

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b py-2 last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  )
}

/**
 * Split into its own component so `useCustomer` is only ever mounted -- and
 * therefore only ever called -- with a real id. `deal.customer_id` is required
 * and non-null on every real `Deal` (`DealCreate`'s own docstring: "a deal
 * without a customer has no economic meaning"), but `deal` itself is `undefined`
 * for the render or two before `useDeal` resolves -- during which a naive
 * `useCustomer(deal?.customer_id ?? '')` at the top of `DealDetail` would call
 * `useCustomer('')`. `features/people`'s own `$personId.tsx` hit exactly this
 * danger first: `/api/customers/{customer_id}` with an empty path segment does
 * not match that route, Starlette's default trailing-slash redirect lands the
 * request on plain `/api/customers` instead -- the *list* endpoint, with an
 * absolute URL that escapes the Vite dev proxy entirely -- and it still resolves
 * 200 with nothing to show for it. Mounting this only from inside the `if
 * (!deal) return ...` guard below, where `deal.customer_id` is guaranteed a real
 * id, is the same fix `LinkedCustomerRow` (people/$personId.tsx) already applies.
 */
function DealCustomerCard({ customerId }: { customerId: string }) {
  const customer = useCustomer(customerId)
  return (
    <Card>
      <CardContent className="pt-6">
        <h2 className="mb-3 font-semibold">Cliente</h2>
        <Row label="Ragione sociale" value={customer.data?.ragione_sociale ?? '…'} />
        <Row label="P.IVA" value={customer.data ? displayNative(customer.data.partita_iva) : '…'} />
      </CardContent>
    </Card>
  )
}

export function DealDetail() {
  const { dealId } = useParams({ from: '/app/deal/$dealId' })
  const navigate = useNavigate()
  const canWrite = useCanWrite()
  const [editing, setEditing] = useState(false)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  const schema = useEntitySchema('deal')
  const { data: deal, isLoading, isError, error } = useDeal(dealId)
  const stages = useStages()
  const update = useUpdateDeal(dealId)
  const remove = useDeleteDeal()

  if (isLoading) return <Skeleton className="m-8 h-96" />
  // See `routes/app/clienti/$customerId.tsx`'s identical guard for the full
  // reasoning: without this, a 500/502/dropped connection reads as "Deal non
  // trovato." exactly like a genuine 404 does, since both leave `deal` undefined
  // once loading ends. `toProblem(error).status` is the one place that is never
  // ambiguous; only a real 404 keeps this screen's own wording.
  if (isError) {
    if (toProblem(error).status === 404) return <p className="p-8">Deal non trovato.</p>
    return (
      <div className="p-8">
        <QueryErrorBanner error={error} />
      </div>
    )
  }
  if (!deal) return <p className="p-8">Deal non trovato.</p>

  const custom = schema.data?.custom_fields ?? []
  const stage = stages.data?.find((item) => item.id === deal.pipeline_stage_id)

  function archive() {
    if (!deal) return
    // Soft delete or not, the UI itself offers no visible undo (restoring today
    // means calling `POST /api/deals/{id}/restore` directly, not a button here)
    // -- a plain confirm is a cheap guard against a misclick, not a client-side
    // re-implementation of any server rule. Mirrors `CustomerDetail`/
    // `PersonDetail`'s own `archive`.
    const confirmed = window.confirm(
      `Archiviare ${deal.nome}? Il deal non comparirà più negli elenchi, ma i dati restano e l'operazione è reversibile.`,
    )
    if (!confirmed) return

    remove.mutate(deal.id, {
      onSuccess: () => {
        toast.success('Deal archiviato')
        void navigate({ to: '/app/deal' })
      },
      onError: (error) => toast.error(toProblem(error).detail),
    })
  }

  return (
    <>
      <EntityDetailLayout
        title={deal.nome}
        subtitle="Deal"
        entityType="deal"
        entityId={dealId}
        actions={
          canWrite && (
            <>
              <Button
                variant="outline"
                onClick={() => {
                  setProblem(null)
                  setEditing(true)
                }}
              >
                <Pencil className="mr-2 size-4" />
                Modifica
              </Button>
              <Button variant="destructive" onClick={archive} disabled={remove.isPending}>
                <Trash2 className="mr-2 size-4" />
                Archivia
              </Button>
            </>
          )
        }
        overview={
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardContent className="pt-6">
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="font-semibold">Stato</h2>
                  {stage && (
                    <Badge variant={stage.tipo === 'open' ? 'secondary' : 'default'}>
                      {stage.nome}
                    </Badge>
                  )}
                </div>
                <Row label="Valore previsto" value={formatMoney(deal.valore_previsto)} />
                <Row label="Probabilità" value={`${deal.probabilita}%`} />
                <Row label="Chiusura prevista" value={formatDate(deal.data_chiusura_prevista)} />
              </CardContent>
            </Card>

            <Card>
              <CardContent className="pt-6">
                <h2 className="mb-3 font-semibold">Preventivo</h2>
                <Row label="Ore preventivate" value={formatHours(deal.ore_preventivate)} />
                <Row label="Valore preventivato" value={formatMoney(deal.valore_preventivato)} />
                <p className="mt-3 text-xs text-muted-foreground">
                  Il confronto preventivo/consuntivo arriva nello slice 4, insieme al time
                  tracking.
                </p>
              </CardContent>
            </Card>

            {custom.length > 0 && (
              <Card className="lg:col-span-2">
                <CardContent className="pt-6">
                  <h2 className="mb-3 font-semibold">Campi personalizzati</h2>
                  {custom.map((field) => (
                    <Row
                      key={field.key}
                      label={field.label}
                      value={renderFieldValue(field, deal.custom_fields[field.key])}
                    />
                  ))}
                </CardContent>
              </Card>
            )}

            {deal.note && (
              <Card className="lg:col-span-2">
                <CardContent className="pt-6">
                  <h2 className="mb-3 font-semibold">Note</h2>
                  <p className="whitespace-pre-wrap text-sm">{deal.note}</p>
                </CardContent>
              </Card>
            )}
          </div>
        }
        links={<DealCustomerCard customerId={deal.customer_id} />}
      />

      <DealForm
        title="Modifica deal"
        open={editing}
        onOpenChange={setEditing}
        customFields={custom}
        initial={dealToFormValues(deal)}
        problem={problem}
        busy={update.isPending}
        onSubmit={(values) => {
          setProblem(null)
          update.mutate(values, {
            onSuccess: () => {
              setEditing(false)
              toast.success('Deal aggiornato')
            },
            onError: (error) => setProblem(toProblem(error)),
          })
        }}
      />
    </>
  )
}

export const Route = createFileRoute('/app/deal/$dealId')({ component: DealDetail })
