/**
 * The accrual period of an invoice (ORB-61) as the two date inputs hold it: two ISO
 * strings, either of which may still be empty because nobody has filled it in.
 *
 * Its own module rather than living beside `AccrualPeriodFields`: eslint's
 * `react-refresh/only-export-components` refuses a file exporting both a component and
 * a plain function, the same reason `lineDraft.ts` sits beside `InvoiceLinesEditor`.
 */
export interface AccrualPeriodDraft {
  competenza_da: string
  competenza_a: string
}

export function emptyAccrualPeriod(): AccrualPeriodDraft {
  return { competenza_da: '', competenza_a: '' }
}

/**
 * What the form checks before asking, in the server's own terms: both ends or neither,
 * and the start not after the end. `InvoiceCreate` and `InvoiceUpdate` refuse the same
 * two shapes with a 422; the sentence here saves the round trip and sits next to the
 * inputs it is about.
 *
 * ISO dates are compared as strings. `YYYY-MM-DD` is zero-padded and big-endian, so `>`
 * on the strings orders them as dates without building a `Date`, which would reopen
 * the UTC-midnight trap `lib/dates.ts` documents.
 */
export function validateAccrualPeriod(draft: AccrualPeriodDraft): string | undefined {
  const da = draft.competenza_da.trim()
  const a = draft.competenza_a.trim()
  if (da === '' && a === '') return undefined
  if (da === '' || a === '') return 'Il periodo di competenza richiede sia l’inizio sia la fine.'
  if (da > a) return 'La fine del periodo di competenza non può precedere l’inizio.'
  return undefined
}

/**
 * The pair as `InvoiceUpdate` takes it: `null`, never an omitted key. On a PATCH an
 * omitted key means "unchanged", and a person who cleared both dates meant "no period",
 * which is the same distinction `InvoiceLinesEditor` draws for an emptied discount.
 */
export function accrualPeriodBody(draft: AccrualPeriodDraft): {
  competenza_da: string | null
  competenza_a: string | null
} {
  const da = draft.competenza_da.trim()
  const a = draft.competenza_a.trim()
  return { competenza_da: da === '' ? null : da, competenza_a: a === '' ? null : a }
}
