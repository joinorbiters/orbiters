import { Checkbox } from '@/components/ui/checkbox'
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
import type { FieldDefinition } from '@/lib/schema'

interface Props {
  field: FieldDefinition
  value: unknown
  onChange: (value: unknown) => void
  error?: string
}

const EMPTY = '—'

/** Shared by both the label above a control and the label beside a checkbox. Always
 *  the semantic `destructive` token (the AA-compliant Watermelon variant every
 *  `aria-invalid` state in components/ui already uses — see styles/tokens.css),
 *  never the raw brand `--color-watermelon` that AppShell/login reserve for
 *  decorative accents: this asterisk is small body text, not a logo. */
function RequiredMark() {
  return <span className="ml-1 text-destructive">*</span>
}

/** One definition in, the right control out. This is what makes a field added at
 *  runtime work in every form without touching the frontend. */
export function DynamicFieldRenderer({ field, value, onChange, error }: Props) {
  const id = `field-${field.key}`
  const invalid = Boolean(error)

  return (
    <div className="space-y-2">
      {field.type !== 'checkbox' && (
        <Label htmlFor={id}>
          {field.label}
          {field.required && <RequiredMark />}
        </Label>
      )}

      {(() => {
        switch (field.type) {
          case 'textarea':
            return (
              <Textarea
                id={id}
                rows={4}
                aria-invalid={invalid}
                value={(value as string) ?? ''}
                onChange={(event) => onChange(event.target.value)}
              />
            )
          case 'number':
          case 'currency':
            return (
              <Input
                id={id}
                type="number"
                step={field.type === 'currency' ? '0.01' : 'any'}
                aria-invalid={invalid}
                value={(value as string) ?? ''}
                onChange={(event) => onChange(event.target.value)}
              />
            )
          case 'date':
            return (
              <Input
                id={id}
                type="date"
                aria-invalid={invalid}
                value={(value as string) ?? ''}
                onChange={(event) => onChange(event.target.value)}
              />
            )
          case 'url':
            return (
              <Input
                id={id}
                type="url"
                placeholder="https://"
                aria-invalid={invalid}
                value={(value as string) ?? ''}
                onChange={(event) => onChange(event.target.value)}
              />
            )
          case 'checkbox':
            return (
              <div className="flex items-center gap-2">
                <Checkbox
                  id={id}
                  aria-invalid={invalid}
                  checked={Boolean(value)}
                  onCheckedChange={(checked) => onChange(checked === true)}
                />
                <Label htmlFor={id} className="font-normal">
                  {field.label}
                  {field.required && <RequiredMark />}
                </Label>
              </div>
            )
          case 'select':
            return (
              <Select value={(value as string) ?? ''} onValueChange={onChange}>
                <SelectTrigger id={id} aria-invalid={invalid} className="w-full">
                  <SelectValue placeholder="Seleziona…" />
                </SelectTrigger>
                <SelectContent>
                  {field.options.map((option) => (
                    <SelectItem key={option} value={option}>
                      {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )
          case 'multiselect': {
            const selected = Array.isArray(value) ? (value as string[]) : []
            return (
              <div aria-invalid={invalid} className="flex flex-wrap gap-3 rounded-md border p-3 aria-invalid:border-destructive">
                {field.options.map((option) => (
                  <label key={option} className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={selected.includes(option)}
                      onCheckedChange={(checked) =>
                        onChange(
                          checked === true
                            ? [...selected, option]
                            : selected.filter((item) => item !== option),
                        )
                      }
                    />
                    {option}
                  </label>
                ))}
              </div>
            )
          }
          default:
            return (
              <Input
                id={id}
                aria-invalid={invalid}
                value={(value as string) ?? ''}
                onChange={(event) => onChange(event.target.value)}
              />
            )
        }
      })()}

      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  )
}

/** `value` is the ISO "YYYY-MM-DD" string a date field always stores (see
 *  packages/core/src/pigrocrm/core/fields/validator.py's `_coerce_date`, which
 *  calls `date.fromisoformat(...).isoformat()` — never a full timestamp).
 *
 *  `new Date("2026-08-06")` parses that as UTC midnight; formatting it with
 *  `Intl.DateTimeFormat` then renders in whichever zone the browser is in. East of
 *  Greenwich that is still 6 August, but anywhere *behind* UTC (all of the
 *  Americas) UTC midnight is still the *previous* evening, so the formatted date
 *  silently loses a day. Building the `Date` from its year/month/day parts in
 *  local time instead means both the construction and the formatting happen in the
 *  same zone, so the calendar day survives no matter where this code runs. */
function formatIsoDateItalian(value: string): string {
  const [year, month, day] = value.split('-').map(Number)
  // The backend's own contract (see the comment above) guarantees all three, but
  // `noUncheckedIndexedAccess` has no way to know that from a `.split` result --
  // and an actually-malformed value is exactly when falling back to the raw string
  // beats either throwing out of a read-only cell or silently formatting "NaN/NaN".
  if (year === undefined || month === undefined || day === undefined) return value
  return new Intl.DateTimeFormat('it-IT').format(new Date(year, month - 1, day))
}

/** The read-only counterpart, used by tables and detail panels.
 *
 *  The absence check is intentionally `=== null || === undefined || === ''`, never
 *  a falsiness check (`!value`): `0`, `false` and the currency string `"0.00"` are
 *  all real, present values — `!0` is `true` in JavaScript, which would render a
 *  deal worth nothing exactly like a deal nobody has priced yet. The backend made
 *  this same mistake once, in `is_blank` (fields/validator.py) — it now special-
 *  cases `False`/`0` as present for exactly this reason, and this function has to
 *  agree with it or the same value would read as "empty" in a table and "provided"
 *  everywhere else. An empty array gets the same treatment for `multiselect`: the
 *  backend never actually persists `[]` (an empty selection is "absent" there too,
 *  see `is_blank`), but a caller handing this function a fresh `[]` before that
 *  round-trip should not see "" where every other empty state reads as "—". */
export function renderFieldValue(field: FieldDefinition, value: unknown): string {
  if (value === null || value === undefined || value === '') return EMPTY
  if (Array.isArray(value) && value.length === 0) return EMPTY

  switch (field.type) {
    // `useGrouping: 'always'` is load-bearing, not decoration: the ICU data backing
    // `Intl.NumberFormat` resolves `it-IT`'s *default* ("auto") grouping to CLDR's
    // "min2" strategy, which withholds the thousands separator until the integer
    // part has five digits or more (verified directly: plain `Intl.NumberFormat
    // ('it-IT').format(1234)` renders "1234", no separator, on this stack's Node/ICU
    // version, while `9999 -> "9999"` and `12345 -> "12.345"` show exactly where the
    // cutover sits). Every Italian reader still expects "1.234,56 €" starting at four
    // digits, so grouping is forced on rather than left to that cutover.
    case 'currency':
      return new Intl.NumberFormat('it-IT', {
        style: 'currency',
        currency: 'EUR',
        useGrouping: 'always',
      }).format(Number(value))
    case 'number':
      return new Intl.NumberFormat('it-IT', { useGrouping: 'always' }).format(Number(value))
    case 'date':
      return formatIsoDateItalian(String(value))
    case 'checkbox':
      return value ? 'Sì' : 'No'
    case 'multiselect':
      return Array.isArray(value) ? value.join(', ') : String(value)
    default:
      return String(value)
  }
}
