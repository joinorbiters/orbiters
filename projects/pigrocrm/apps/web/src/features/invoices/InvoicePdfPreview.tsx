import { useQuery } from '@tanstack/react-query'
import { FileText } from 'lucide-react'
import { useEffect } from 'react'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchWithRefresh, toProblem } from '@/lib/api'
import { queryKeys } from '@/lib/query'
import type { Invoice } from './queries'

/**
 * The document itself, beside its numbers (ORB-30).
 *
 * The bytes come through `GET /api/invoices/{id}/pdf`, the same authenticated path the
 * «PDF» button downloads from: the API is the only place authorisation exists on either
 * storage backend (slice 2 §5), so an `<iframe src="/api/...">` would be wrong twice --
 * it could not carry the tenant prefix and the refresh, and the route answers
 * `Content-Disposition: attachment`, which a frame would turn into a download. A blob
 * URL is what the browser's own viewer shows, and it is revoked when the page leaves.
 *
 * The cache key carries `pdf_document_id`: «Rigenera documenti» stores a new version
 * under the same document, and the preview must not keep the old bytes for `staleTime`.
 */
export function InvoicePdfPreview({ invoice }: { invoice: Invoice }) {
  const documentId = invoice.pdf_document_id
  const pdf = useQuery({
    queryKey: queryKeys.invoicePdf(invoice.id, documentId ?? ''),
    enabled: documentId !== null,
    // The blob URL is derived from the bytes, so it lives and dies with the query's data.
    // Structural sharing would compare two URLs and keep the first: turned off.
    structuralSharing: false,
    queryFn: async () => {
      const response = await fetchWithRefresh(`/api/invoices/${invoice.id}/pdf`)
      if (!response.ok) {
        const payload: unknown = await response.json().catch(() => null)
        throw toProblem(payload, response.status)
      }
      return URL.createObjectURL(await response.blob())
    },
  })

  const url = pdf.data
  useEffect(() => {
    if (!url) return
    return () => URL.revokeObjectURL(url)
  }, [url])

  return (
    <aside
      aria-label="Anteprima PDF"
      className="bg-muted/40 flex min-h-[32rem] flex-col overflow-hidden rounded-xl border xl:sticky xl:top-6 xl:h-[calc(100vh-11rem)]"
    >
      {documentId === null ? (
        <Empty invoice={invoice} />
      ) : pdf.isError ? (
        <div className="p-4">
          <QueryErrorBanner error={pdf.error} />
        </div>
      ) : pdf.isPending || !url ? (
        <Skeleton className="m-4 flex-1" />
      ) : (
        <iframe
          title={`Anteprima PDF ${invoice.tipo === 'proforma' ? 'proforma' : 'fattura'}`}
          // `#toolbar=0` is a hint the Chromium and Firefox viewers honour and Safari
          // ignores: the bar's own «PDF» button is the download, so the viewer's chrome
          // adds nothing here.
          src={`${url}#toolbar=0&navpanes=0`}
          className="h-full w-full flex-1 border-0"
        />
      )}
    </aside>
  )
}

/**
 * No PDF is not an error: a draft has no document until emission produces one, and a
 * proforma has none until «PDF proforma» renders it. Saying so is the whole content.
 */
function Empty({ invoice }: { invoice: Invoice }) {
  const text =
    invoice.tipo === 'proforma'
      ? 'Il PDF della proforma non è ancora stato generato: «PDF proforma» lo produce.'
      : invoice.stato === 'bozza'
        ? 'Il PDF si genera all’emissione. Fino ad allora la bozza è solo numeri.'
        : 'Nessun PDF archiviato per questo documento. «Rigenera documenti» lo produce.'
  return (
    <div className="text-muted-foreground m-auto flex max-w-xs flex-col items-center gap-3 p-6 text-center text-sm">
      <FileText className="size-8" aria-hidden="true" />
      <p>{text}</p>
    </div>
  )
}
