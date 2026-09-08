import { toIsoDate } from '@/lib/dates'
import { clearedNativeValue, type FieldDefinition } from '@/lib/schema'
import type { TimeEntry } from './queries'

/**
 * The editable native columns, as `FieldDefinition`s so `DynamicFieldRenderer` draws
 * them -- the same idiom `DealForm`/`CustomerForm` use. `deal_id` is absent: it comes
 * from the route, and reassigning an hour to another deal is not something this screen
 * offers. `user_id` is absent too: it is the logged-in user on create, and reassigning
 * it is an admin operation with no picker control (`FieldType` has no user type).
 */
export const NATIVE_FIELDS: FieldDefinition[] = [
  { key: 'data', label: 'Data', type: 'date', required: true, options: [] },
  { key: 'ore', label: 'Ore', type: 'number', required: true, options: [] },
  { key: 'descrizione', label: 'Descrizione', type: 'textarea', required: true, options: [] },
  { key: 'fatturabile', label: 'Fatturabile', type: 'checkbox', required: false, options: [] },
  {
    key: 'tariffa_applicata',
    label: 'Tariffa (€/h, lascia vuoto per usare quella predefinita)',
    type: 'number',
    required: false,
    options: [],
  },
  { key: 'note_interne', label: 'Note interne', type: 'textarea', required: false, options: [] },
]

const NATIVE_FIELD_KEYS = NATIVE_FIELDS.map((field) => field.key)

/** Fields the backend freezes once the entry is on an issued invoice (§4.3 --
 *  `FROZEN_WHEN_BILLED` in `timetracking/service.py`). The form hides them rather than
 *  letting the user type into a control whose value the server will refuse: an
 *  `ImmutableField` after pressing Salva is a worse explanation than a field that is
 *  simply not there. */
export const LOCKED_KEYS = new Set([
  'data',
  'ore',
  'descrizione',
  'fatturabile',
  'tariffa_applicata',
])

/**
 * Two namespaces, decided once at seed time and never re-derived at submit -- copies
 * `DealFormValues` exactly, for the same reason: provenance is structural. A native
 * column clears on the spelling its type calls for (`clearedNativeValue`: `""` for
 * text, `null` for everything else); a custom field clears on `null` and only on
 * `null`; an omitted key clears nothing.
 */
export interface TimeEntryFormValues {
  native: Record<string, unknown>
  custom: Record<string, unknown>
}

/**
 * Today's date, and billable, because that is what somebody opening "Registra ore" is
 * almost always recording. Built from the local calendar parts rather than
 * `new Date().toISOString().slice(0, 10)`: `toISOString` converts to UTC first, so
 * anywhere east of Greenwich late in the evening the form would open pre-filled with
 * *tomorrow* -- and `_check_not_future` refuses a future date, so the user would meet a
 * server error on a date they never chose. The mirror image of the read-side trap
 * `formatIsoDateItalian` (@/lib/dates) closes.
 */
export function defaultFormValues(today: Date = new Date()): TimeEntryFormValues {
  return { native: { fatturabile: true, data: toIsoDate(today) }, custom: {} }
}

/**
 * Builds the form's starting state from an entry that already exists.
 *
 * Deliberately not `{ ...entry, ...entry.custom_fields }`: a `TimeEntryRead` also
 * carries `id`, `tariffa_origine`, `valore_riga`, `invoice_line_id`, `created_at` and
 * the rest, none of which `TimeEntryUpdate` accepts -- sending them back would 422 on
 * every edit. Walking exactly `NATIVE_FIELD_KEYS` keeps the round trip to what the form
 * is allowed to send; `custom_fields` is copied whole into its own namespace, archived
 * keys included, so `_update_custom_fields` can carry them over untouched.
 */
export function timeEntryToFormValues(entry: TimeEntry): TimeEntryFormValues {
  const native: Record<string, unknown> = {}
  for (const key of NATIVE_FIELD_KEYS) {
    native[key] = (entry as unknown as Record<string, unknown>)[key]
  }
  return { native, custom: { ...entry.custom_fields } }
}

/** Mirrors `is_blank` in `fields/validator.py` and every other form's own helper:
 *  `null`/`undefined`, a whitespace-only string, or an empty array mean "no value";
 *  `false` and `0` are real values. */
export function isBlank(value: unknown): boolean {
  if (value === null || value === undefined) return true
  if (typeof value === 'string') return value.trim() === ''
  if (Array.isArray(value)) return value.length === 0
  return false
}

/**
 * Turns the two namespaces into the body the API takes.
 *
 * A plain module function, not a method on the form, so `TimeEntryForm.tsx` exports
 * only its component: `react-refresh/only-export-components` is live on
 * `src/features/**`, and the three older forms each bought their way out with a
 * per-file eslint `allowExportNames` override. Splitting the value layer off instead is
 * the same coupling made explicit rather than waived -- `NATIVE_FIELDS`, the locked
 * keys and the payload rules are one thing, and the dialog that renders them is
 * another.
 */
export function toRequestBody(
  values: TimeEntryFormValues,
  options: { initial?: TimeEntryFormValues; locked: boolean; isRenderedCustomKey: (key: string) => boolean },
): Record<string, unknown> {
  const { initial, locked, isRenderedCustomKey } = options

  const native: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(values.native)) {
    if (locked && LOCKED_KEYS.has(key)) continue
    if (!isBlank(value)) {
      native[key] = value
    } else if (!isBlank(initial?.native[key])) {
      // The user cleared a native column that held a value: say so explicitly, or
      // the old value survives untouched. `clearedNativeValue` picks the spelling
      // from the column's type -- `descrizione` and `note_interne` clear on `""`,
      // `data`, `ore` and `tariffa_applicata` on `null`. Clearing a rate is the one
      // that matters most here: it is a deliberate "this hour has no price", and
      // `TimeEntryService.update` records it as `origine = "assente"` rather than
      // letting the deal's rate quietly take over.
      native[key] = clearedNativeValue(NATIVE_FIELDS, key)
    }
  }

  const custom: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(values.custom)) {
    // A stored value whose definition is archived: omit the key and
    // `_update_custom_fields` carries it over untouched.
    if (!isRenderedCustomKey(key)) continue
    if (!isBlank(value)) {
      custom[key] = value
    } else if (!isBlank(initial?.custom[key])) {
      custom[key] = null
    }
  }

  return { ...native, custom_fields: custom }
}
