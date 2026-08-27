import { Plus, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useCostCategories, type CostCategory } from '@/features/costs/queries'
import { toProblem } from '@/lib/api'
import {
  useArchiveCostCategory,
  useCreateCostCategory,
  useSeedCostCategories,
  useUnarchiveCostCategory,
  useUpdateCostCategory,
} from './queries.timetracking'

/**
 * One row, its own component, because the rename mutation is built from the category's
 * id: `useUpdateCostCategory(id)` inside the parent's `.map` would be a hook call per
 * row -- a variable number of them, in a variable order, which is exactly what the
 * rules of hooks forbid.
 */
function CategoryRow({
  category,
  onProblem,
}: {
  category: CostCategory
  onProblem: (message: string) => void
}) {
  const [nome, setNome] = useState(category.nome)
  const rename = useUpdateCostCategory(category.id)
  const archive = useArchiveCostCategory()
  const unarchive = useUnarchiveCostCategory()
  const dirty = nome.trim() !== category.nome

  return (
    <li className="flex flex-wrap items-center gap-3 p-3">
      <Input
        aria-label={`Nome della categoria ${category.nome}`}
        value={nome}
        onChange={(event) => setNome(event.target.value)}
        className="max-w-xs"
      />
      {/* The code, beside the name and never in a control: it is the category's
          identity, the thing a report or an import keys on, and the reason renaming is
          safe at all. A seeded category has one; one created here does not. */}
      <code className="text-xs text-muted-foreground">{category.code ?? '—'}</code>
      {category.archiviata && <span className="text-xs text-muted-foreground">archiviata</span>}
      <div className="ml-auto flex gap-2">
        {dirty && (
          <Button
            size="sm"
            disabled={rename.isPending}
            onClick={() =>
              rename.mutate(
                { nome: nome.trim() },
                {
                  onSuccess: () => toast.success('Categoria rinominata'),
                  onError: (error) => onProblem(toProblem(error).detail),
                },
              )
            }
          >
            Salva
          </Button>
        )}
        {category.archiviata ? (
          <Button
            size="sm"
            variant="outline"
            disabled={unarchive.isPending}
            onClick={() =>
              unarchive.mutate(category.id, {
                onSuccess: () => toast.success('Categoria ripristinata'),
                onError: (error) => onProblem(toProblem(error).detail),
              })
            }
          >
            Ripristina
          </Button>
        ) : (
          <Button
            size="sm"
            variant="outline"
            disabled={archive.isPending}
            onClick={() =>
              archive.mutate(category.id, {
                onSuccess: () => toast.success('Categoria archiviata'),
                onError: (error) => onProblem(toProblem(error).detail),
              })
            }
          >
            Archivia
          </Button>
        )}
      </div>
    </li>
  )
}

export function CostCategoriesPanel() {
  const [includeArchived, setIncludeArchived] = useState(false)
  const [open, setOpen] = useState(false)
  const [nome, setNome] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  // Separate from `problem` on purpose: the list banner sits behind the dialog overlay,
  // so a create that fails there would report itself somewhere nobody can see.
  const [dialogProblem, setDialogProblem] = useState<string | null>(null)

  const categories = useCostCategories(includeArchived)
  const create = useCreateCostCategory()
  const seed = useSeedCostCategories()

  if (categories.isError) return <QueryErrorBanner error={categories.error} />

  const rows = [...(categories.data ?? [])].sort((a, b) => a.posizione - b.posizione)
  const empty = rows.length === 0 && !categories.isLoading

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="font-semibold">Categorie di costo</h2>
          <p className="text-sm text-muted-foreground">
            Identità stabile: il nome si può rinominare, il codice no. Una categoria non si
            elimina, si archivia — i costi già registrati continuano a mostrarne il nome, e
            solo le categorie attive si possono scegliere per un costo nuovo.
          </p>
        </div>
        <div className="flex gap-2">
          {/* Only on an empty list: the endpoint is idempotent, so a second press would
              be harmless, but a button that does nothing visible is worse than one that
              is not there. */}
          {empty && (
            <Button
              variant="outline"
              disabled={seed.isPending}
              onClick={() =>
                seed.mutate(undefined, {
                  onSuccess: (created) =>
                    toast.success(`${created.length} categorie predefinite create`),
                  onError: (error) => setProblem(toProblem(error).detail),
                })
              }
            >
              <Sparkles className="mr-2 size-4" />
              Crea le categorie predefinite
            </Button>
          )}
          <Button
            onClick={() => {
              setDialogProblem(null)
              setNome('')
              setOpen(true)
            }}
          >
            <Plus className="mr-2 size-4" />
            Nuova categoria
          </Button>
        </div>
      </div>

      {problem && (
        <p
          role="alert"
          className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {problem}
        </p>
      )}

      <div className="flex items-center gap-2">
        <Checkbox
          id="includi-archiviate"
          checked={includeArchived}
          onCheckedChange={(checked) => setIncludeArchived(checked === true)}
        />
        <Label htmlFor="includi-archiviate" className="font-normal">
          Includi archiviate
        </Label>
      </div>

      <ul className="divide-y rounded-lg border">
        {rows.map((category) => (
          <CategoryRow key={category.id} category={category} onProblem={setProblem} />
        ))}
        {empty && (
          <li className="p-3 text-sm text-muted-foreground">Nessuna categoria configurata.</li>
        )}
      </ul>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nuova categoria</DialogTitle>
          </DialogHeader>
          {dialogProblem && (
            <p
              role="alert"
              className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {dialogProblem}
            </p>
          )}
          <div className="space-y-2">
            <Label htmlFor="categoria-nome">Nome</Label>
            <Input
              id="categoria-nome"
              value={nome}
              onChange={(event) => setNome(event.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Una categoria creata qui non ha un codice: il codice esiste solo sulle categorie
              predefinite, che i rapporti riconoscono per codice e non per nome.
            </p>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Annulla
            </Button>
            <Button
              disabled={create.isPending}
              onClick={() =>
                create.mutate(
                  { nome, posizione: rows.length },
                  {
                    onSuccess: () => {
                      toast.success('Categoria creata')
                      setOpen(false)
                    },
                    onError: (error) => setDialogProblem(toProblem(error).detail),
                  },
                )
              }
            >
              {create.isPending ? 'Creazione…' : 'Crea'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
