import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ExternalLink } from 'lucide-react'
import { ApiError, admin } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { Empty, Header } from './lists'

/**
 * Which spaces of PigroCRM exist and whose they are (ORB-142). The list is the CRM's
 * registry as the hub's API relays it; the one thing the hub adds is the member behind an
 * address, whose name links to their card. An address nobody applied with stays an
 * address, and nothing here creates, renames or deletes a space.
 */
export function AdminPigro() {
  const list = useQuery({ queryKey: ['pigro-spaces'], queryFn: () => admin.pigroSpaces() })
  const failure = list.error instanceof ApiError ? list.error : null
  return (
    <>
      <Header title="Istanze Pigro" count={list.data?.totale} />
      {list.isError ? (
        // A 503 or a 502 arrives with its own sentence; anything else gets the generic one.
        <Empty>{failure && failure.status >= 500 ? failure.message : 'Non riesco a leggere il registro.'}</Empty>
      ) : list.isPending ? (
        <Empty>Caricamento…</Empty>
      ) : list.data.items.length === 0 ? (
        <Empty>Nessuna istanza ancora.</Empty>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr className="border-b">
              <th className="px-6 py-2 font-medium">Spazio</th>
              <th className="px-3 py-2 font-medium">Di chi è</th>
              <th className="px-6 py-2 text-right font-medium">Creato</th>
            </tr>
          </thead>
          <tbody>
            {list.data.items.map((space) => (
              <tr key={space.slug} className="border-b last:border-0 hover:bg-muted">
                <td className="px-6 py-2.5">
                  <a
                    href={space.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 font-medium hover:underline"
                  >
                    {space.slug}
                    <ExternalLink className="size-3.5 text-muted-foreground" aria-hidden="true" />
                  </a>
                </td>
                <td className="px-3 py-2.5">
                  {space.membro ? (
                    <>
                      <Link
                        to="/admin/freelance/$id"
                        params={{ id: space.membro.id }}
                        className="font-medium hover:underline"
                      >
                        {space.membro.nome} {space.membro.cognome}
                      </Link>
                      <p className="text-xs text-muted-foreground">{space.owner_email}</p>
                    </>
                  ) : (
                    <p>{space.owner_email}</p>
                  )}
                </td>
                <td className="px-6 py-2.5 text-right text-muted-foreground">{formatDate(space.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}
