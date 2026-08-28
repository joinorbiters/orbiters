/**
 * The one percentage formatter of this feature, in a module of its own.
 *
 * It sits here rather than beside `PnlRows` because a module that exports a component
 * may not also export a plain function -- `react-refresh/only-export-components`, which
 * this codebase satisfies by splitting rather than by widening an eslint override each
 * time. `lib/dates.ts` was extracted for the same reason and states it in its own
 * docstring.
 */

// A plain decimal formatter with the `%` appended by hand, not `style: 'percent'`.
// Two reasons. ICU's it-IT percent style renders "89,00%" with no space at all
// (checked directly on this stack: the code points are 38 39 2c 30 30 25), while every
// screen of this product writes "89,00 %"; and `style: 'percent'` expects a *fraction*,
// so feeding it the API's `89.00` would mean dividing by 100 here -- arithmetic on an
// economic field, which is the one thing this feature is not allowed to do.
// `formatRateValue` already appends its own "€/h" for the same reason.
//
// `useGrouping: 'always'`, never the ICU default: it-IT withholds the thousands
// separator until the integer part has five digits, and a four-figure percentage losing
// its separator on one screen is the inconsistency every other formatter in this
// product already forces grouping on to avoid.
const percent = new Intl.NumberFormat('it-IT', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  useGrouping: 'always',
})

export const NOT_COMPUTABLE = 'non calcolabile'

/**
 * `null` renders as «non calcolabile», never as `0,00 %`.
 *
 * Zero per cent means "everything I earned went out in costs"; a null denominator means
 * nothing has been earned yet. Two different facts, and this is the last place they
 * could be flattened after the backend took care to keep them apart -- `percentage_of`
 * returns `None` for a zero denominator and performs no division at all in that case.
 *
 * `Number()` here is a *display* conversion of a value that has already stopped being
 * arithmetic: the API divided and rounded, and this only groups its digits. The same
 * exemption `formatMoneyValue` documents, and it holds for the same reason -- nothing
 * in this module adds, divides, compares or accumulates.
 */
export function formatPercent(value: string | null): string {
  return value === null ? NOT_COMPUTABLE : `${percent.format(Number(value))} %`
}
