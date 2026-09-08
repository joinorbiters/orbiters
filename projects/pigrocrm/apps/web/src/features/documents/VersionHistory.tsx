import { useState } from 'react'
import { Download, RefreshCw } from 'lucide-react'
import { QueryErrorBanner } from '@/components/QueryErrorBanner'
import { Button } from '@/components/ui/button'
import { toProblem, type ProblemDetail } from '@/lib/api'
import { downloadDocument, useDocumentVersions, useRegenerateVersion } from './queries'

const BYTES_PER_KILOBYTE = 1024

/**
 * Bytes as the browser's own locale would write them. `Intl.NumberFormat` with a
 * byte unit does the rounding, so nothing here does arithmetic on a size that could
 * drift from what the server reported.
 *
 * Divides by 1024, not 1000, even though the unit it asks `Intl` to label is the
 * (decimal) "kilobyte": confirmed live -- `12345` bytes has to read "12,1 kB", the
 * conventional binary-kilobyte figure this product's own file browsers (Finder,
 * Explorer) already show, and `12345 / 1000` rounds to "12,3 kB" instead, which is
 * simply the wrong number for the same bytes.
 */
function formatSize(bytes: number): string {
  return new Intl.NumberFormat('it-IT', {
    style: 'unit',
    unit: bytes >= BYTES_PER_KILOBYTE ? 'kilobyte' : 'byte',
    maximumFractionDigits: 1,
  }).format(bytes >= BYTES_PER_KILOBYTE ? bytes / BYTES_PER_KILOBYTE : bytes)
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('it-IT', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * Every version, newest first. Nothing here overwrites anything: regeneration adds a
 * new version rather than replacing the one it was built from, which is what makes
 * "una versione di sei mesi prima si rigenera identica" a check anyone can run.
 */
export function VersionHistory({ documentId }: { documentId: string }) {
  const versions = useDocumentVersions(documentId)
  const regenerate = useRegenerateVersion(documentId)
  const [problem, setProblem] = useState<ProblemDetail | null>(null)

  if (versions.isError) return <QueryErrorBanner error={versions.error} />

  // `GET /api/documents/{document_id}/versions` answers a bare, newest-first list
  // (`response_model=list[DocumentVersionRead]`, documents.py router) -- not a
  // cursor page like the documents/templates list endpoints -- so there is no
  // `.items` to unwrap here.
  const items = versions.data ?? []

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium">Storico versioni</h3>
      {problem && (
        <p
          role="alert"
          className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {problem.detail}
        </p>
      )}
      {items.length === 0 && <p className="text-muted-foreground">Nessuna versione.</p>}
      {items.length > 0 && (
        <ul className="divide-y rounded-lg border">
          {items.map((version) => (
            <li key={version.id} className="flex items-center gap-3 px-4 py-3">
              <span className="w-10 font-medium">v{version.numero}</span>
              <span className="flex-1 text-sm text-muted-foreground">
                {formatDateTime(version.created_at)} · {formatSize(version.dimensione)}
              </span>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Scarica la versione ${version.numero}`}
                onClick={() => {
                  setProblem(null)
                  void downloadDocument(documentId, version.numero).catch((error: unknown) =>
                    setProblem(toProblem(error)),
                  )
                }}
              >
                <Download className="h-4 w-4" />
              </Button>
              {/* Only a version generated from a template can be regenerated: an
                  uploaded scan has no template and no variables to rebuild it from,
                  and the server refuses that call by name. */}
              {version.template_id !== null && (
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Rigenera la versione ${version.numero}`}
                  disabled={regenerate.isPending}
                  onClick={() => {
                    setProblem(null)
                    regenerate.mutate(version.numero, {
                      onError: (error: unknown) => setProblem(toProblem(error)),
                    })
                  }}
                >
                  <RefreshCw className="h-4 w-4" />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
