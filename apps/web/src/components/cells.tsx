import { Calendar } from 'lucide-react'
import type { ReactNode } from 'react'
import { formatIsoDateItalian } from '@/lib/dates'
import { cn } from '@/lib/utils'

/** The same em dash every absent value in this product renders as -- `displayNative`
 *  in the three feature column files, `formatMoney`/`formatDate` in the formatters. */
const EMPTY = '—'

/**
 * A date, with the small calendar icon the reference puts before every one (design
 * spec §4).
 *
 * Takes the API's own `YYYY-MM-DD` string, not a pre-formatted one, and goes through
 * `lib/dates.ts` -- the one module that knows that `new Date('2026-01-01')` is UTC
 * midnight and formats a day early anywhere behind UTC. Every date column in the
 * product already formatted through an equivalent of it (`formatIsoDateItalian` in
 * deals/costs/solleciti, its twin in `features/invoices/format.ts`), so the rendered
 * string is unchanged by this cell; what changes is that the icon exists and that
 * "absent" is one decision instead of four.
 *
 * An absent date carries no icon: a calendar beside a dash claims there is a date.
 * `''` counts as absent for the same reason `displayNative` treats it so -- a cleared
 * native column can hold either spelling.
 */
export function DateCell({ value }: { value: string | null }) {
  if (value === null || value === '') return <span className="text-muted-foreground">{EMPTY}</span>
  return (
    <span className="inline-flex items-center gap-1.5">
      <Calendar aria-hidden="true" className="size-3.5 shrink-0 text-muted-foreground" />
      {formatIsoDateItalian(value)}
    </span>
  )
}

/**
 * A money figure, right-aligned on tabular digits so a column of amounts lines up on
 * the cent.
 *
 * Takes the *formatted* figure, not a decimal string: the feature that owns the number
 * owns its formatting, and those formatters legitimately differ (`features/invoices/
 * format.ts` parses the API string into integer cents; `features/time/columns.tsx` and
 * `features/deals/columns.tsx` keep their own, each with its own `null` meaning). A
 * second money formatter in shared table code is how two screens start disagreeing
 * about the same euro -- and `lib/no-float-money.test.ts` exists because the tempting
 * shortcut is a float. So this cell adds no arithmetic of any kind.
 *
 * Alignment still needs the column's `meta.align: 'right'` for the *header* to sit over
 * the digits: see `DataTableColumnMeta`. This class is what keeps the figure hard right
 * inside the cell even when the column is wider than the number.
 */
export function MoneyCell({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn('block text-right tabular-nums', className)}>{children}</span>
}

/**
 * Up to two initials for the chip: the first letter of each of the first two words.
 *
 * Two, not more: «Acme Srl» reads as `CS`, and a chip of four
 * letters is no longer a chip. Words are split on any run of whitespace so a double
 * space cannot produce an empty initial, and the result is uppercased because a
 * lowercase ragione sociale would otherwise give a chip that looks like a typo.
 */
function initialsOf(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => word.charAt(0))
    .join('')
    .toUpperCase()
}

/**
 * The first column of a table when the row *is* somebody: an initials chip on Paper
 * beside the name, with an optional quiet second line (design spec §4, "prima colonna
 * con avatar/iniziali dove c'è un'entità").
 *
 * Initials rather than an image because this product stores no avatars for customers,
 * people or deals -- and the chip is `aria-hidden`: the name is right there in words,
 * so announcing "AS ACME Srl" would read the same thing twice, once as nonsense.
 *
 * A nameless record still has to render a row, so an empty name is the same em dash
 * every other empty cell shows, with no chip: an empty circle beside a dash reads as a
 * broken image rather than as absence.
 */
export function EntityCell({ name, sub }: { name: string; sub?: string | null }) {
  const label = name.trim()
  if (label === '') return <span className="text-muted-foreground">{EMPTY}</span>

  return (
    <span className="flex items-center gap-3">
      <span
        data-slot="entity-initials"
        aria-hidden="true"
        className="flex size-8 shrink-0 items-center justify-center rounded-full bg-[var(--color-paper)] text-xs font-medium text-foreground"
      >
        {initialsOf(label)}
      </span>
      <span className="flex min-w-0 flex-col leading-tight">
        <span className="truncate font-medium">{label}</span>
        {sub !== null && sub !== undefined && sub !== '' && sub !== EMPTY ? (
          <span className="truncate text-xs text-muted-foreground">{sub}</span>
        ) : null}
      </span>
    </span>
  )
}
