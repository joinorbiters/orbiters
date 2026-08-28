import { useId } from 'react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { firstDayOfMonth, lastDayOfMonth, type Period } from './period'

/**
 * The window every `/analisi` report is read over, chosen a month at a time.
 *
 * Months rather than days, because that is the granularity of the question: an invoice
 * is dated to a month, a period lock covers a month, and a report over "the 9th to the
 * 23rd" is one nobody asked for. The value handed back is still a pair of dates, since
 * that is what the API takes -- the *to* end is the last day of the chosen month, never
 * the first, so a March-to-March report does not silently exclude March.
 */
export function PeriodPicker({
  value,
  onChange,
}: {
  value: Period
  onChange: (value: Period) => void
}) {
  const fromId = useId()
  const toId = useId()

  /** A month input cleared with the keyboard fires `change` with an empty string. There
   *  is no window to report over then, and the endpoint's `from`/`to` are mandatory, so
   *  the previous one stays until a real month replaces it -- rather than sending `''`
   *  and getting a 422 the user never asked for. */
  const move = (end: 'from' | 'to', month: string) => {
    if (!month) return
    onChange({ ...value, [end]: end === 'from' ? firstDayOfMonth(month) : lastDayOfMonth(month) })
  }

  return (
    <div className="flex flex-wrap items-end gap-4">
      <div className="grid gap-1.5">
        <Label htmlFor={fromId}>Da</Label>
        <Input
          id={fromId}
          type="month"
          // Sliced back to `YYYY-MM` rather than held as separate state: one source of
          // truth for the window, so the control can never show a month the query is not
          // being made over.
          value={value.from.slice(0, 7)}
          onChange={(event) => move('from', event.target.value)}
        />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor={toId}>A</Label>
        <Input
          id={toId}
          type="month"
          value={value.to.slice(0, 7)}
          onChange={(event) => move('to', event.target.value)}
        />
      </div>
    </div>
  )
}
