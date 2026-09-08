import { Button } from '@/components/ui/button'
import { currentMonth, presetQuarter, presetYear, type Periodo } from './periodo'

/**
 * Two dates and three presets. Every change is handed straight back to the caller, which
 * puts it in the URL — nothing here is component state, because a period held locally is a
 * period a shared link cannot carry (§4).
 */
export function PeriodPicker({
  periodo,
  onChange,
}: {
  periodo: Periodo
  onChange: (next: Periodo) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="text-sm text-muted-foreground" htmlFor="periodo-da">
        Dal
      </label>
      <input
        id="periodo-da"
        type="date"
        value={periodo.da}
        onChange={(event) => onChange({ ...periodo, da: event.target.value })}
        className="rounded-md border bg-background px-2 py-1 text-sm"
      />
      <label className="text-sm text-muted-foreground" htmlFor="periodo-a">
        al
      </label>
      <input
        id="periodo-a"
        type="date"
        value={periodo.a}
        onChange={(event) => onChange({ ...periodo, a: event.target.value })}
        className="rounded-md border bg-background px-2 py-1 text-sm"
      />
      <Button variant="ghost" size="sm" onClick={() => onChange(currentMonth())}>
        Mese
      </Button>
      <Button variant="ghost" size="sm" onClick={() => onChange(presetQuarter())}>
        Trimestre
      </Button>
      <Button variant="ghost" size="sm" onClick={() => onChange(presetYear())}>
        Anno
      </Button>
    </div>
  )
}
