import { useState } from 'react'
import { DynamicForm } from '@/components/DynamicForm'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { ProblemDetail } from '@/lib/api'
import type { FieldDefinition } from '@/lib/schema'
import type { Customer } from './queries'

const NATIVE_FIELDS: FieldDefinition[] = [
  { key: 'ragione_sociale', label: 'Ragione sociale', type: 'text', required: true, options: [] },
  { key: 'partita_iva', label: 'P.IVA', type: 'text', required: false, options: [] },
  { key: 'codice_fiscale', label: 'Codice fiscale', type: 'text', required: false, options: [] },
  { key: 'codice_sdi', label: 'Codice SDI', type: 'text', required: false, options: [] },
  { key: 'pec', label: 'PEC', type: 'text', required: false, options: [] },
  { key: 'indirizzo', label: 'Indirizzo', type: 'text', required: false, options: [] },
  { key: 'cap', label: 'CAP', type: 'text', required: false, options: [] },
  { key: 'comune', label: 'Comune', type: 'text', required: false, options: [] },
  { key: 'provincia', label: 'Provincia', type: 'text', required: false, options: [] },
  // Freeform text, not a `select`: CustomerCreate/Update place no enum on either
  // field (plain `SafeStr`, max_length only) -- offering a client-side dropdown of
  // guessed options would let the UI reject a value the backend, and an MCP agent
  // writing through the same service, both accept without complaint.
  { key: 'nazione', label: 'Nazione', type: 'text', required: false, options: [] },
  { key: 'email', label: 'Email', type: 'text', required: false, options: [] },
  { key: 'telefono', label: 'Telefono', type: 'text', required: false, options: [] },
  { key: 'sito_web', label: 'Sito web', type: 'url', required: false, options: [] },
  { key: 'stato', label: 'Stato', type: 'text', required: false, options: [] },
  { key: 'note', label: 'Note', type: 'textarea', required: false, options: [] },
]

const NATIVE_FIELD_KEYS = NATIVE_FIELDS.map((field) => field.key)

// `nazione` pre-filled to match `CustomerCreate.nazione`'s own server-side default
// (customers/schemas.py: `Field(default="IT", ...)`) -- a convenience, not a rule:
// leaving it blank omits the key from the payload entirely (see `submit` below) and
// the server fills in the exact same default either way.
const DEFAULT_CREATE_VALUES: Record<string, unknown> = { nazione: 'IT' }

/**
 * Builds the form's starting state from a real, already-saved customer.
 *
 * Deliberately not `{ ...customer, ...customer.custom_fields }`: `customer` also
 * carries `id`, `created_at` and `updated_at`, and `CustomerUpdate` declares
 * `model_config = ConfigDict(extra="forbid")` (customers/schemas.py) -- sending
 * those three straight back would 422 with "extra fields not permitted" on every
 * single edit, since none of them is a field `CustomerUpdate` recognises. Listing
 * exactly the editable native keys, then spreading `custom_fields` on top, is what
 * keeps the round trip to only what the form is actually allowed to send.
 */
export function customerToFormValues(customer: Customer): Record<string, unknown> {
  const native: Record<string, unknown> = {}
  for (const key of NATIVE_FIELD_KEYS) {
    native[key] = (customer as unknown as Record<string, unknown>)[key]
  }
  return { ...native, ...customer.custom_fields }
}

/** Mirrors `is_blank` in packages/core/src/pigrocrm/core/fields/validator.py:
 *  `null`/`undefined`, a whitespace-only string, or an empty array all mean "no
 *  value" -- `false` and `0` do not, they are real values. `submit` below needs this
 *  same line drawn on the client for exactly the same reason `is_blank` is public
 *  and reused everywhere on the server: two different definitions of "empty" is how
 *  a required check and a clear-vs-untouched check start disagreeing. */
function isBlank(value: unknown): boolean {
  if (value === null || value === undefined) return true
  if (typeof value === 'string') return value.trim() === ''
  if (Array.isArray(value)) return value.length === 0
  return false
}

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  customFields: FieldDefinition[]
  initial?: Record<string, unknown>
  problem?: ProblemDetail | null
  busy?: boolean
  onSubmit: (values: Record<string, unknown>) => void
  title: string
}

export function CustomerForm({
  open,
  onOpenChange,
  customFields,
  initial,
  problem,
  busy,
  onSubmit,
  title,
}: Props) {
  const [values, setValues] = useState<Record<string, unknown>>(initial ?? DEFAULT_CREATE_VALUES)

  // This component stays mounted across opens -- only `Dialog`'s own visibility
  // toggles (see the list/detail routes: `open={open}` on an always-rendered
  // `<CustomerForm>`, not a conditional `{open && <CustomerForm />}`, which would
  // lose Radix's closing animation) -- so `useState`'s initializer alone, which
  // only ever runs on first mount, is not enough: reopening "Nuovo cliente" a
  // second time would still show the first customer's already-submitted values,
  // and reopening "Modifica" after the customer changed underneath it would still
  // show the stale copy. Comparing against the previous `open` value during render
  // and resetting synchronously is React's own documented pattern for this exact
  // case ("Adjusting state when a prop changes", react.dev) -- deliberately not a
  // `useEffect`: that would need `initial` in its dependency array to be honest
  // about what it reads, but the caller recomputes a brand-new `initial` object
  // every render (`customerToFormValues(customer)` has no stable identity), so the
  // effect would re-fire on every keystroke and wipe out whatever the user just
  // typed.
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) setValues(initial ?? DEFAULT_CREATE_VALUES)
  }

  function submit() {
    const custom: Record<string, unknown> = {}
    const native: Record<string, unknown> = {}
    const isCustomKey = (key: string) => customFields.some((field) => field.key === key)

    for (const [key, value] of Object.entries(values)) {
      const target = isCustomKey(key) ? custom : native
      if (!isBlank(value)) {
        target[key] = value
        continue
      }
      if (!isBlank(initial?.[key])) {
        // The user cleared a field that used to hold a value -- say so explicitly
        // instead of dropping the key, or the old value survives untouched. Native
        // columns and custom fields disagree on what "clear" means on the wire
        // (packages/core/src/pigrocrm/core/customers/service.py):
        //   - a native column clears on `""` (`CustomerUpdate.model_dump
        //     (exclude_none=True)` keeps an empty string, only `None` is dropped);
        //   - a custom field clears only on an explicit `null`
        //     (`_update_custom_fields` reads it as "remove this key") -- `""`
        //     there is `is_blank`, which a non-required field just quietly skips,
        //     leaving the previously-stored value in place.
        // Sending the wrong one of the two for a given key would compile, run, and
        // silently fail to clear anything.
        target[key] = isCustomKey(key) ? null : ''
      }
      // else: blank now, blank (or never set) before -- nothing changed, so there
      // is nothing to say. This is also what keeps a freshly-required custom field
      // this edit never touched from being reported as "cleared".
    }
    onSubmit({ ...native, custom_fields: custom })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        <DynamicForm
          fields={[...NATIVE_FIELDS, ...customFields]}
          values={values}
          onChange={(key, value) => setValues((previous) => ({ ...previous, [key]: value }))}
          problem={problem}
        />

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Annulla
          </Button>
          <Button onClick={submit} disabled={busy}>
            {busy ? 'Salvataggio…' : 'Salva'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
