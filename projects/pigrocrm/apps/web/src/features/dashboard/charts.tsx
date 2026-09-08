import { cn } from '@/lib/utils'

/**
 * Four shapes, no charting library: big numbers, horizontal bars as CSS widths, one
 * sparkline, one table. A library costs 40-100 KB for these four in a project that gave
 * its landing page a 40 KB budget (slice 5 §9.4), and it would bring its own palette while
 * `tokens.css` is the single source of colour and has tests behind it.
 *
 * **Every shape renders an equivalent table**, and the table is not a fallback: it is the
 * accessible rendering, and the visual mark is decoration layered on top with
 * `aria-hidden`. A chart without a table is a figure a screen reader does not read (§13).
 *
 * That is also what makes one set of five hues legal for both colour modes. Colour here
 * encodes *nothing*: every bar sits in its own row beside its own label and its own value
 * as text, so a reader who cannot separate two hues has lost no information. The five
 * tokens are below the 3:1-on-both-surfaces bar a mark carrying meaning would have to
 * clear, and `styles/tokens.test.ts` records exactly what that costs and what would have
 * to change first if a shape ever made the hue the only thing telling two series apart.
 *
 * **Nothing here parses a number.** Values arrive as the strings the API sent, already
 * formatted, and `ratio` arrives as a number the *server* derived. These components format
 * nothing and add nothing -- `src/test/no-browser-arithmetic.test.ts` is what keeps that
 * true.
 */

const CHART_TONES = 5

const EMPTY = 'Nessun dato nel periodo.'

function toneColor(tone: number): string {
  // 1-based, wrapping. `var(--chart-n)` and never a literal colour. A sixth row is the
  // first colour again rather than a generated sixth hue: the palette is fixed, and the
  // row label is what carries identity anyway.
  const index = (((tone - 1) % CHART_TONES) + CHART_TONES) % CHART_TONES
  return `var(--chart-${index + 1})`
}

function widthPercent(ratio: number): string {
  // Clamped rather than trusted: a ratio above 1 would draw a bar past its row, and a
  // negative one would vanish silently. `Math.min`/`Math.max` on a number the server
  // computed is not parsing an API string -- the guard forbids coercion, not clamping.
  const clamped = Math.max(0, Math.min(1, ratio))
  return `${(clamped * 100).toFixed(2)}%`
}

export function BigNumber({
  label,
  value,
  hint,
  tone = 'neutral',
}: {
  label: string
  value: string
  hint?: string
  tone?: 'neutral' | 'accent'
}) {
  return (
    <div role="group" aria-label={label} className="overflow-hidden rounded-lg border bg-card">
      {/* The accent is a mark, not coloured text. --chart-1 as a foreground measures
          2.86:1 on the light card, well under the 4.5:1 a number has to clear, and a
          figure the reader squints at is a worse dashboard than an unemphasised one.
          The rule above the card carries the emphasis and the value keeps ink. */}
      {tone === 'accent' && (
        <div aria-hidden="true" className="h-1" style={{ backgroundColor: toneColor(1) }} />
      )}
      <div className={cn('p-4', tone === 'accent' && 'pt-3')}>
        <p className="text-sm text-muted-foreground">{label}</p>
        {/* Proportional figures, not `tabular-nums`: at this size tabular digits give
            every glyph the width of a `0` and a short value reads loose. Tabular figures
            belong in the columns below, where numbers have to line up. */}
        <p className="mt-1 text-2xl font-semibold">{value}</p>
        {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      </div>
    </div>
  )
}

function EmptyChart({ caption }: { caption: string }) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-sm font-medium">{caption}</p>
      <p className="mt-2 text-sm text-muted-foreground">{EMPTY}</p>
    </div>
  )
}

export type BarRow = {
  label: string
  value: string
  /** 0..1, computed by the server. Clamped here, never derived here. */
  ratio: number
  /** 1..5, mapped to --chart-1..5. */
  tone: number
}

export function BarRows({ caption, rows }: { caption: string; rows: BarRow[] }) {
  if (rows.length === 0) return <EmptyChart caption={caption} />
  return (
    <div className="overflow-x-auto rounded-lg border bg-card p-4">
      <table className="w-full text-sm">
        <caption className="mb-2 text-left text-sm font-medium">{caption}</caption>
        {/* The header names the two columns for a screen reader and would be pure noise on
            screen, where the caption and the row labels already say it. */}
        <thead className="sr-only">
          <tr>
            <th scope="col">Voce</th>
            <th scope="col">Valore</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <th scope="row" className="py-1 pr-3 text-left font-normal">
                {row.label}
              </th>
              <td className="py-1">
                <div className="flex items-center gap-2">
                  <div className="h-2 min-w-24 flex-1 rounded-sm bg-muted">
                    {/* Square at the baseline, rounded at the data end: the shape says
                        which side the bar grows from without a second axis to read. */}
                    <div
                      data-testid="bar-fill"
                      aria-hidden="true"
                      className="h-2 rounded-r-[3px]"
                      style={{
                        width: widthPercent(row.ratio),
                        backgroundColor: toneColor(row.tone),
                      }}
                    />
                  </div>
                  <span className="shrink-0 tabular-nums">{row.value}</span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export type SparkPoint = {
  label: string
  value: string
  /** 0..1, computed by the server. */
  ratio: number
}

const SPARK_WIDTH = 240
const SPARK_HEIGHT = 48

export function Sparkline({ caption, points }: { caption: string; points: SparkPoint[] }) {
  if (points.length === 0) return <EmptyChart caption={caption} />

  // `points.length - 1` is a subtraction on an array length, not on an API value, and it
  // is guarded against a single point -- which would otherwise divide by zero and produce
  // `NaN` coordinates that render as an invisible line rather than as an error.
  const step = points.length > 1 ? SPARK_WIDTH / (points.length - 1) : 0
  const path = points
    .map((point, index) => {
      const x = index * step
      const y = SPARK_HEIGHT - Math.max(0, Math.min(1, point.ratio)) * SPARK_HEIGHT
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  return (
    <div className="overflow-x-auto rounded-lg border bg-card p-4">
      <svg
        data-testid="sparkline-svg"
        aria-hidden="true"
        viewBox={`0 0 ${SPARK_WIDTH} ${SPARK_HEIGHT}`}
        className="h-12 w-full"
        preserveAspectRatio="none"
      >
        {/* `preserveAspectRatio="none"` stretches the box to the card's width, which is
            what lets a fixed viewBox serve any number of points -- but it stretches the
            stroke with it, so a 2px line renders thin on the verticals and thick on the
            horizontals. `vector-effect` is what keeps the stroke 2px in device pixels
            while the geometry still scales. */}
        <path
          d={path}
          fill="none"
          stroke="var(--chart-2)"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <table className="mt-2 w-full text-sm">
        <caption className="mb-2 text-left text-sm font-medium">{caption}</caption>
        <thead>
          <tr>
            {points.map((point) => (
              <th key={point.label} scope="col" className="font-normal text-muted-foreground">
                {point.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            {points.map((point) => (
              <td key={point.label} className="tabular-nums">
                {point.value}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  )
}
