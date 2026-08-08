import type { ColumnDef } from '@tanstack/react-table'
import { Archive, ArchiveRestore, Plus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DataTable, type DataTableFeatures } from '@/components/DataTable'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { fieldErrorFrom, toProblem, type ProblemDetail } from '@/lib/api'
import type { EntityType, FieldType } from '@/lib/schema'
import {
  useArchiveFieldDefinition,
  useCreateFieldDefinition,
  useFieldDefinitions,
  useUnarchiveFieldDefinition,
  type FieldDefinitionRecord,
} from './queries'

const ENTITIES: { value: EntityType; label: string }[] = [
  { value: 'customer', label: 'Cliente' },
  { value: 'person', label: 'Persona' },
  { value: 'deal', label: 'Deal' },
]

const TYPES: { value: FieldType; label: string }[] = [
  { value: 'text', label: 'Testo' },
  { value: 'textarea', label: 'Testo lungo' },
  { value: 'number', label: 'Numero' },
  { value: 'currency', label: 'Valuta' },
  { value: 'date', label: 'Data' },
  { value: 'select', label: 'Selezione singola' },
  { value: 'multiselect', label: 'Selezione multipla' },
  { value: 'checkbox', label: 'Sì / No' },
  { value: 'url', label: 'URL' },
]

const NEEDS_OPTIONS = new Set<FieldType>(['select', 'multiselect'])

// Every field name `FieldDefinitionCreate` (fields/schemas.py) can attribute a
// `validation_failed` 422 to -- used to decide whether a problem attaches to one
// of this dialog's own controls or falls back to the banner above them. See
// `DynamicForm.tsx`'s `unattributedMessage` for the identical reasoning; this is
// the same idea applied to a hand-built dialog instead of a `FieldDefinition[]`-
// driven one, since "type" here is a fixed nine-way choice with Italian labels
// no generic `select` control can render (`DynamicFieldRenderer`'s `select`
// shows each `option` string as its own label, which would mean showing the raw
// English enum values -- "text", "currency" -- instead of "Testo"/"Valuta").
const ALWAYS_RENDERED_FIELDS = ['entity_type', 'key', 'label', 'field_type', 'required', 'position']

/**
 * Unlike `DynamicForm`'s identically-purposed `unattributedMessage`, "known"
 * here cannot be a fixed list: the Opzioni control only renders at all when
 * `fieldType` is `select`/`multiselect` (`NEEDS_OPTIONS`), so a `field: 'options'`
 * problem is attachable only in that state. Naming `showsOptions` explicitly
 * (rather than re-deriving it from a captured `fieldType` closure) keeps this
 * function honest about the one thing that actually changes what it can attach
 * to -- getting this wrong the other way (treating 'options' as always
 * attachable) would silently drop the server's message the moment a `text`
 * field's create request somehow came back naming 'options': the paragraph that
 * would show it lives inside the same `NEEDS_OPTIONS.has(fieldType)` guard as the
 * control itself, so an unattributed fallback is the only way that message would
 * ever reach the user in that state.
 */
function unattributed(problem: ProblemDetail | null, showsOptions: boolean): string | null {
  if (!problem) return null
  const fieldError = fieldErrorFrom(problem)
  if (!fieldError) return problem.detail
  const known = showsOptions ? [...ALWAYS_RENDERED_FIELDS, 'options'] : ALWAYS_RENDERED_FIELDS
  return known.includes(fieldError.field) ? null : problem.detail
}

export function FieldsPanel() {
  const [entityType, setEntityType] = useState<EntityType>('customer')
  const [open, setOpen] = useState(false)
  const [key, setKey] = useState('')
  const [label, setLabel] = useState('')
  const [fieldType, setFieldType] = useState<FieldType>('text')
  const [optionsText, setOptionsText] = useState('')
  const [required, setRequired] = useState(false)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  const fields = useFieldDefinitions(entityType)
  const create = useCreateFieldDefinition()
  const archive = useArchiveFieldDefinition()
  const unarchive = useUnarchiveFieldDefinition()

  const fieldError = problem ? fieldErrorFrom(problem) : null
  const banner = unattributed(problem, NEEDS_OPTIONS.has(fieldType))

  function openDialog() {
    setProblem(null)
    setKey('')
    setLabel('')
    setFieldType('text')
    setOptionsText('')
    setRequired(false)
    setOpen(true)
  }

  function submit() {
    setProblem(null)
    create.mutate(
      {
        entity_type: entityType,
        key,
        label,
        field_type: fieldType,
        options: NEEDS_OPTIONS.has(fieldType)
          ? optionsText
              .split('\n')
              .map((line) => line.trim())
              .filter(Boolean)
          : [],
        required,
        position: fields.data?.length ?? 0,
      },
      {
        onSuccess: () => {
          toast.success('Campo creato')
          setOpen(false)
        },
        onError: (error) => setProblem(toProblem(error)),
      },
    )
  }

  const columns: ColumnDef<DataTableFeatures, FieldDefinitionRecord>[] = [
    { header: 'Etichetta', accessorKey: 'label' },
    { header: 'Chiave', id: 'key', cell: (info) => <code>{info.row.original.key}</code> },
    {
      header: 'Tipo',
      id: 'field_type',
      accessorFn: (row) => TYPES.find((type) => type.value === row.field_type)?.label ?? row.field_type,
    },
    {
      header: 'Obbligatorio',
      id: 'required',
      accessorFn: (row) => (row.required ? 'Sì' : 'No'),
    },
    {
      header: 'Stato',
      id: 'archived',
      cell: (info) => (
        <Badge variant={info.row.original.archived ? 'secondary' : 'default'}>
          {info.row.original.archived ? 'Archiviato' : 'Attivo'}
        </Badge>
      ),
    },
    {
      header: '',
      id: 'actions',
      cell: (info) => {
        const field = info.row.original
        // Archiving and restoring are both single-click, with no confirmation
        // dialog: unlike an irreversible action (a pipeline-stage delete, a
        // token revoke), the other half of this pair is always one more click
        // away, in this same row -- a misclick costs nothing to undo.
        return field.archived ? (
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Ripristina ${field.label}`}
            onClick={() =>
              unarchive.mutate(field.id, {
                onSuccess: () => toast.success('Campo ripristinato'),
                onError: (error) => toast.error(toProblem(error).detail),
              })
            }
          >
            <ArchiveRestore className="size-4" />
          </Button>
        ) : (
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Archivia ${field.label}`}
            onClick={() =>
              archive.mutate(field.id, {
                onSuccess: () => toast.success('Campo archiviato'),
                onError: (error) => toast.error(toProblem(error).detail),
              })
            }
          >
            <Archive className="size-4" />
          </Button>
        )
      },
    },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div className="space-y-2">
          <Label htmlFor="entity">Entità</Label>
          <Select value={entityType} onValueChange={(value) => setEntityType(value as EntityType)}>
            <SelectTrigger id="entity" className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ENTITIES.map((entity) => (
                <SelectItem key={entity.value} value={entity.value}>
                  {entity.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button onClick={openDialog}>
          <Plus className="mr-2 size-4" />
          Nuovo campo
        </Button>
      </div>

      <DataTable
        columns={columns}
        data={fields.data ?? []}
        isLoading={fields.isLoading}
        isError={fields.isError}
        error={fields.error}
        emptyMessage="Nessun campo personalizzato per questa entità."
      />

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Nuovo campo</DialogTitle>
            <DialogDescription>
              Il tipo non è modificabile dopo la creazione: per cambiarlo, archivia il campo e
              creane uno nuovo. I valori già inseriti restano leggibili e non vengono toccati.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {banner && (
              <p
                role="alert"
                className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                {banner}
              </p>
            )}

            <div className="space-y-2">
              <Label htmlFor="field-label">Etichetta</Label>
              <Input
                id="field-label"
                aria-invalid={fieldError?.field === 'label'}
                value={label}
                onChange={(event) => {
                  setLabel(event.target.value)
                  // The API slugifies anyway (`slugify_key`, fields/schemas.py); pre-filling
                  // only makes the eventual result predictable before submit, never a promise
                  // this exact string is what gets stored.
                  if (!key) setKey(event.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '_'))
                }}
              />
              {fieldError?.field === 'label' && (
                <p className="text-sm text-destructive">{fieldError.message}</p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="field-key">Chiave</Label>
              <Input
                id="field-key"
                aria-invalid={fieldError?.field === 'key'}
                value={key}
                onChange={(event) => setKey(event.target.value)}
              />
              {fieldError?.field === 'key' && (
                <p className="text-sm text-destructive">{fieldError.message}</p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="field-type">Tipo</Label>
              <Select value={fieldType} onValueChange={(value) => setFieldType(value as FieldType)}>
                <SelectTrigger id="field-type" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TYPES.map((type) => (
                    <SelectItem key={type.value} value={type.value}>
                      {type.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {NEEDS_OPTIONS.has(fieldType) && (
              <div className="space-y-2">
                <Label htmlFor="field-options">Opzioni (una per riga)</Label>
                <Textarea
                  id="field-options"
                  rows={4}
                  aria-invalid={fieldError?.field === 'options'}
                  value={optionsText}
                  onChange={(event) => setOptionsText(event.target.value)}
                />
                {fieldError?.field === 'options' && (
                  <p className="text-sm text-destructive">{fieldError.message}</p>
                )}
              </div>
            )}

            <div className="flex items-center gap-2">
              <Checkbox
                id="field-required"
                checked={required}
                onCheckedChange={(checked) => setRequired(checked === true)}
              />
              <Label htmlFor="field-required" className="font-normal">
                Obbligatorio
              </Label>
            </div>
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Annulla
            </Button>
            <Button onClick={submit} disabled={create.isPending}>
              {create.isPending ? 'Creazione…' : 'Crea'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
