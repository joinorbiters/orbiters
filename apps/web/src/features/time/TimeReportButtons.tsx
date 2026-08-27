import { toIsoMonth } from '@/lib/dates'
import { Download, FileSpreadsheet } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { timeReportUrl } from './queries'

/**
 * Two formats, two recipients (§2.1): the PDF is attached to the invoice, the XLSX gets
 * filtered by whoever has to check it. Plain anchors, not fetches: the browser
 * downloads the file itself, so the bytes never pass through JavaScript, and being
 * same-origin the session cookie travels with the request without a token in a query
 * string.
 */
export function TimeReportButtons({ dealId }: { dealId: string }) {
  // `toIsoMonth`, never `toISOString().slice(0, 7)` -- see @/lib/dates for why.
  const [mese, setMese] = useState(() => toIsoMonth(new Date()))

  return (
    <div className="flex flex-wrap items-end gap-3">
      <div className="space-y-2">
        <Label htmlFor="time-report-mese">Rapporto ore del mese</Label>
        <Input
          id="time-report-mese"
          type="month"
          value={mese}
          onChange={(event) => setMese(event.target.value)}
          className="w-40"
        />
      </div>
      <Button asChild variant="outline">
        <a href={timeReportUrl(dealId, mese, 'pdf')}>
          <Download className="mr-2 size-4" />
          PDF
        </a>
      </Button>
      <Button asChild variant="outline">
        <a href={timeReportUrl(dealId, mese, 'xlsx')}>
          <FileSpreadsheet className="mr-2 size-4" />
          XLSX
        </a>
      </Button>
    </div>
  )
}
