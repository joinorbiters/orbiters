import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Plus, Search } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { DataTable } from '@/components/DataTable'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { CustomerForm } from '@/features/customers/CustomerForm'
import { buildCustomerColumns } from '@/features/customers/columns'
import { useCreateCustomer, useCustomers } from '@/features/customers/queries'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { useCanWrite } from '@/lib/auth'
import { useEntitySchema } from '@/lib/schema'

function CustomersPage() {
  const navigate = useNavigate()
  const canWrite = useCanWrite()
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(false)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  const schema = useEntitySchema('customer')
  const customers = useCustomers({ search: search || undefined })
  const create = useCreateCustomer()

  // Recomputed every render, not memoised: `schema.data?.custom_fields` only
  // changes when the schema query itself refetches, and `buildCustomerColumns`
  // does no work heavier than building a handful of plain objects -- not worth a
  // `useMemo` whose dependency array would just repeat the same query result.
  const columns = buildCustomerColumns(schema.data?.custom_fields ?? [])

  return (
    <div className="p-8">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Clienti</h1>
        {canWrite && (
          <Button
            onClick={() => {
              setProblem(null)
              setOpen(true)
            }}
          >
            <Plus className="mr-2 size-4" />
            Nuovo cliente
          </Button>
        )}
      </header>

      <div className="relative mb-4 max-w-sm">
        <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          className="pl-9"
          placeholder="Cerca per ragione sociale, P.IVA, codice fiscale o email…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      <DataTable
        columns={columns}
        data={customers.data?.items ?? []}
        isLoading={customers.isLoading}
        onRowClick={(row) =>
          void navigate({ to: '/app/clienti/$customerId', params: { customerId: row.id } })
        }
        emptyMessage="Nessun cliente. Creane uno per iniziare."
      />

      <CustomerForm
        title="Nuovo cliente"
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
              toast.success('Cliente creato')
            },
            onError: (error) => setProblem(toProblem(error)),
          })
        }}
      />
    </div>
  )
}

export const Route = createFileRoute('/app/clienti/')({ component: CustomersPage })
