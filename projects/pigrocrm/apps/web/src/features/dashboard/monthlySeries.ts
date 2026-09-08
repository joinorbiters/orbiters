/** The four cash series of the economic charts, in stacking order, with the tile
 *  palette each one wears (see MonthlyBars.tsx for why the brand palette and not a
 *  validated categorical set). */
export type SeriesKey = 'incassato' | 'da_incassare' | 'bozze' | 'costi'

export const SERIES: Record<SeriesKey, { label: string; color: string }> = {
  incassato: { label: 'Ricavi incassati', color: 'var(--color-prussian-blue)' },
  da_incassare: { label: 'Da incassare', color: 'var(--color-royal-gold)' },
  bozze: { label: 'Bozze / proforma', color: 'var(--color-charcoal-blue)' },
  costi: { label: 'Costi passivi', color: 'var(--color-watermelon-strong)' },
}

