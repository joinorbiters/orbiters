import { money } from './format'
import { SERIES, type SeriesKey } from './monthlySeries'
import type { CashMonth } from './queries'

/**
 * Twelve stacked columns, one per month, in the product's own visual system: square
 * tiles on the grid, a 2px surface gap between segments, a legend always present
 * (there are two or four series) and the table view underneath for a screen reader.
 *
 * Heights come from the server (`quote_*`, a share of the tallest month in [0, 1]):
 * the browser never turns an amount string into a number
 * (src/test/no-browser-arithmetic.test.ts); it multiplies a share by a pixel height,
 * which is geometry, not a figure.
 *
 * Series colours are the tile palette, not a validated categorical set: Prussian Blue
 * and Royal Gold sit outside the lightness band a chart palette would want, and the
 * dataviz validator says so. The brand wins here, and the secondary encodings carry
 * identity where colour alone would not -- legend, direct label on the tallest
 * segment of a column, the 2px gaps and the table view.
 */

const MONTHS = ['gen', 'feb', 'mar', 'apr', 'mag', 'giu', 'lug', 'ago', 'set', 'ott', 'nov', 'dic']
const PLOT_HEIGHT = 180

function isZero(value: string): boolean {
  return /^-?0(?:\.0+)?$/.test(value)
}

export function MonthlyBars({
  title,
  months,
  series,
  shares,
}: {
  title: string
  months: CashMonth[]
  series: SeriesKey[]
  shares: 'quote_andamento' | 'quote_proiezione'
}) {
  const empty = months.every((month) => series.every((key) => isZero(month[key])))

  return (
    <figure className="border bg-card p-4" aria-labelledby={`${shares}-title`}>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <figcaption id={`${shares}-title`} className="text-sm font-medium">
          {title}
        </figcaption>
        <ul className="flex flex-wrap gap-4 text-xs text-muted-foreground" aria-label="Legenda">
          {series.map((key) => (
            <li key={key} className="flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className="inline-block size-2.5"
                style={{ backgroundColor: SERIES[key].color }}
              />
              {SERIES[key].label}
            </li>
          ))}
        </ul>
      </div>

      {empty ? (
        <p className="mt-4 text-sm text-muted-foreground">Nessun movimento nell&apos;anno.</p>
      ) : (
        <div
          aria-hidden="true"
          className="mt-4 grid grid-cols-12 items-end gap-2"
          style={{ height: PLOT_HEIGHT }}
        >
          {months.map((month) => {
            // Stacked from the baseline up, in series order; a 2px surface gap between
            // segments, none below the first.
            const segments = series
              .map((key) => ({ key, share: month[shares][key] ?? 0, value: month[key] }))
              .filter((segment) => segment.share > 0)
            const tallest = segments.reduce(
              (best, segment) => (segment.share > best.share ? segment : best),
              segments[0] ?? { key: series[0]!, share: 0, value: '0.00' },
            )
            return (
              <div key={month.mese} className="flex h-full flex-col justify-end gap-0.5">
                {[...segments].reverse().map((segment) => (
                  <div
                    key={segment.key}
                    data-series={segment.key}
                    data-testid="segment"
                    title={`${SERIES[segment.key].label}: ${money(segment.value)}`}
                    className="relative w-full"
                    style={{
                      height: `${Math.max(2, segment.share * PLOT_HEIGHT)}px`,
                      backgroundColor: SERIES[segment.key].color,
                    }}
                  >
                    {segment === tallest && segment.share > 0.35 && (
                      <span
                        className="absolute inset-x-0 top-1 truncate px-1 text-center text-[10px] font-medium"
                        style={{
                          color:
                            segment.key === 'da_incassare'
                              ? 'var(--color-prussian-blue)'
                              : '#ffffff',
                        }}
                      >
                        {money(segment.value)}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )
          })}
        </div>
      )}
      <div aria-hidden="true" className="mt-1 grid grid-cols-12 gap-2 text-center text-xs text-muted-foreground">
        {months.map((month) => (
          <span key={month.mese}>{MONTHS[month.mese - 1]}</span>
        ))}
      </div>

      {/* The table view: the same figures, for a screen reader and for anyone who wants
          the number rather than the bar. Visually collapsed, never absent. */}
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-xs text-muted-foreground">Tabella dei valori</summary>
        <table className="mt-2 w-full text-xs">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th scope="col" className="py-1 pr-2 font-normal">
                Mese
              </th>
              {series.map((key) => (
                <th key={key} scope="col" className="py-1 pr-2 font-normal">
                  {SERIES[key].label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {months.map((month) => (
              <tr key={month.mese}>
                <th scope="row" className="py-1 pr-2 text-left font-normal">
                  {MONTHS[month.mese - 1]} {String(month.anno).slice(2)}
                </th>
                {series.map((key) => (
                  <td key={key} className="py-1 pr-2 tabular-nums">
                    {money(month[key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  )
}
