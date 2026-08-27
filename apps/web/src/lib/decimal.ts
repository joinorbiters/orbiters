/**
 * Exact arithmetic on the decimal strings the API sends.
 *
 * Every `Numeric` column serialises to a JSON **string**, never a number -- which is
 * precisely what lets the browser read the digits instead of routing them through a
 * binary float. `Numeric(12,2)` exists on the backend so money is never a float
 * (`deals/models.py`: "a binary float cannot represent 1234.56 exactly, and that drift
 * is a bug the moment it reaches an invoice"), and summing those values as
 * `sum + Number(value)` in the browser throws that guarantee away.
 *
 * Generalised from `features/deals/columns.tsx`'s own private
 * `centsFromDecimalString`, which now imports from here: three features need it at
 * once (the week grid's row and column totals, the costs panel, the deals Kanban), and
 * a fourth copy is how they start disagreeing.
 *
 * **This is the only arithmetic permitted in the browser in this slice**, and only for
 * hours. Every economic figure -- every P&L row, every margin, every accrued value --
 * arrives from the API already summed (§6), and `no-float-money.test.ts` fails the
 * build if any module adds one.
 *
 * Scale bounds: `Numeric(12,2)` holds at most 10 integer digits, so its hundredths
 * representation is at most 12 digits, far under `Number.MAX_SAFE_INTEGER`'s 16 even
 * summed across thousands of rows. `Numeric(12,6)` is the same 12 digits. Plain
 * `number` integer arithmetic is therefore exact here; nothing needs `BigInt`, only the
 * discipline of never multiplying or dividing a fractional value.
 */

export const MONEY_SCALE = 2
export const HOURS_SCALE = 2

/**
 * `"1234.56"` at scale 2 -> `123456`.
 *
 * Splits the string into its integer and fractional halves as *strings*, parses each
 * separately, and combines with integer arithmetic. The fractional digits are never
 * multiplied -- `Number("0.29") * 100` is `28.999999999999996` in this project's own
 * Node runtime -- and only the whole-number part, already an integer, is scaled.
 */
export function scaledFromDecimalString(value: string, scale: number): number {
  const negative = value.startsWith('-')
  const unsigned = negative ? value.slice(1) : value
  const [wholePart = '', fractionPart = ''] = unsigned.split('.')
  const padded = (fractionPart + '0'.repeat(scale)).slice(0, scale)
  const factor = 10 ** scale
  const scaled = Number(wholePart || '0') * factor + Number(padded || '0')
  return negative ? -scaled : scaled
}

/** `123456` at scale 2 -> `"1234.56"`. The inverse, used once per displayed total. */
export function decimalStringFromScaled(scaled: number, scale: number): string {
  const negative = scaled < 0
  const digits = String(Math.abs(scaled)).padStart(scale + 1, '0')
  const whole = digits.slice(0, digits.length - scale)
  const fraction = digits.slice(digits.length - scale)
  return `${negative ? '-' : ''}${whole}${scale > 0 ? `.${fraction}` : ''}`
}

/**
 * Sums decimal strings exactly and formats the result once, at the end.
 *
 * `null` contributes nothing rather than zero -- the same distinction `formatMoney`
 * draws when it renders a dash instead of `0,00 €` for an unpriced row.
 */
export function sumDecimalStrings(
  values: readonly (string | null)[],
  scale: number,
): string {
  let total = 0
  for (const value of values) {
    if (value !== null) total += scaledFromDecimalString(value, scale)
  }
  return decimalStringFromScaled(total, scale)
}
