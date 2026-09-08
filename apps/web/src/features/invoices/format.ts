import { decimalStringFromScaled, MONEY_SCALE, scaledFromDecimalString } from '@/lib/decimal'
import type { Invoice, InvoiceLine } from './queries'

const EMPTY = '—'

// `useGrouping: 'always'` is mandatory: the default withholds the thousands separator
// below five integer digits, so 1500.00 would print as "1500,00 €".
const euro = new Intl.NumberFormat('it-IT', {
  style: 'currency',
  currency: 'EUR',
  useGrouping: 'always',
})
const quantity = new Intl.NumberFormat('it-IT', { maximumFractionDigits: 6 })
const italianDate = new Intl.DateTimeFormat('it-IT')

/**
 * Integer cents parsed out of the decimal string the API sends.
 *
 * A local copy rather than a shared import, matching the codebase's precedent of a
 * small per-feature display helper (`features/deals/columns.tsx` keeps its own
 * private one too) rather than widening a shared module's public surface.
 */
function centsFromDecimalString(value: string): number {
  const negative = value.startsWith('-')
  const unsigned = negative ? value.slice(1) : value
  const [wholePart, fractionPart = ''] = unsigned.split('.')
  const cents = Number(wholePart || '0') * 100 + Number((fractionPart + '00').slice(0, 2))
  return negative ? -cents : cents
}

export function formatMoney(value: string | null): string {
  return value === null ? EMPTY : euro.format(centsFromDecimalString(value) / 100)
}

export function formatQuantity(value: string | null): string {
  return value === null ? EMPTY : quantity.format(Number(value))
}

export function formatRate(value: string | null): string {
  return value === null ? EMPTY : `${quantity.format(Number(value))}%`
}

/**
 * An ISO date, parsed field by field.
 *
 * Never `new Date('2026-01-01')`: that is UTC midnight, which renders as 31 December
 * anywhere west of Greenwich. It is the same defect as `toISOString()` on the backend,
 * in the other direction, and on an invoice it shows the wrong fiscal year.
 */
export function formatDate(value: string | null): string {
  if (value === null) return EMPTY
  const [year, month, day] = value.split('-').map(Number)
  if (year === undefined || month === undefined || day === undefined) return value
  return italianDate.format(new Date(year, month - 1, day))
}

/**
 * The label a human reads. Two integers joined by a slash is presentation, not
 * business logic -- and a proforma's reference deliberately cannot be produced by this
 * function from a number, because it never has one.
 */
export function formatInvoiceNumber(
  invoice: Pick<Invoice, 'anno' | 'numero' | 'riferimento'>,
): string {
  if (invoice.anno !== null && invoice.numero !== null) return `${invoice.anno}/${invoice.numero}`
  return invoice.riferimento ?? EMPTY
}

/**
 * The sum of the line totals, for the editor's live preview only.
 *
 * The authoritative totals are the ones the API stored; this exists so the editor can
 * show a running figure before saving, and it adds integer cents because
 * `Number('0.29') * 100` is `28.999999999999996`.
 */
export function sumLineTotals(lines: Pick<InvoiceLine, 'prezzo_totale'>[]): string {
  const cents = lines.reduce((sum, line) => sum + centsFromDecimalString(line.prezzo_totale), 0)
  const negative = cents < 0
  const absolute = Math.abs(cents)
  return `${negative ? '-' : ''}${Math.floor(absolute / 100)}.${String(absolute % 100).padStart(2, '0')}`
}

/** A row of the create dialog as the inputs hold it: two decimal strings, either of
 *  which may still be empty because the user is typing. */
interface PricedRow {
  quantita: string
  prezzo_unitario: string
}

/** Only a plain decimal is arithmetic here. Anything else -- a stray letter, a comma,
 *  a half-typed minus -- contributes nothing rather than turning the whole total into
 *  NaN while the user is mid-keystroke. */
const DECIMAL = /^-?\d*\.?\d*$/

/** `FACTOR_DECIMAL_PLACES` in `packages/core/src/pigrocrm/core/invoices/schemas.py`:
 *  `quantita` and `prezzo_unitario` are `Numeric(12, 6)`. */
const FACTOR_SCALE = 6
/** Millionths times cents lands at 10^-8; this brings the product back to cents. */
const FACTOR_TO_CENTS = 1_000_000

/**
 * What a set of typed-in rows would come to, for the create dialog's live figure.
 *
 * The counterpart of `sumLineTotals` for rows that do not exist server-side yet: there
 * is no `prezzo_totale` to add up, so the product has to be formed here. Exact integer
 * arithmetic via `lib/decimal.ts` -- the quantity in millionths (`Numeric(12,6)`, which
 * is what makes 7,5 hours expressible), the price in cents -- and never a float:
 * `Number('0.29') * 100` is `28.999999999999996` in this project's own Node runtime.
 *
 * It is a *preview*, and says so on screen. The authoritative imponibile is the one
 * `InvoiceService` computes and stores: it works at the price's full six decimals and
 * applies the regime's own rules (`_computed_lines`/`_apply_totals`), where this rounds
 * the price to the cent and knows nothing about discounts or VAT. A row priced beyond
 * two decimals can therefore differ from the stored figure by a cent, which is the
 * right trade for a number that exists only to tell the owner they have typed 300 € and
 * not 3.000 €.
 *
 * Bounds: a realistic row (thousands of units, thousands of euro) keeps the product
 * inside `Number.MAX_SAFE_INTEGER`; the columns' own extremes (`Numeric(12,6)` twice
 * over) do not, and `overflows_money_column` on the backend is what refuses those --
 * this figure would visibly lose precision first, on a document the server will not
 * accept either.
 */
export function previewImponibile(rows: readonly PricedRow[]): string {
  let cents = 0
  for (const row of rows) {
    const quantity = row.quantita.trim()
    const price = row.prezzo_unitario.trim()
    if (quantity === '' || price === '') continue
    if (!DECIMAL.test(quantity) || !DECIMAL.test(price)) continue
    cents += Math.round(
      (scaledFromDecimalString(quantity, FACTOR_SCALE) *
        scaledFromDecimalString(price, MONEY_SCALE)) /
        FACTOR_TO_CENTS,
    )
  }
  return decimalStringFromScaled(cents, MONEY_SCALE)
}
