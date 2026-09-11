import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { admin } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { Empty, Figure, Header } from './lists'

/**
 * Who comes back in (ORB-158): every login the magic link wrote down, the distinct
 * members behind them against everybody on file, the last week, and the latest ones by
 * name. Read-only: the rows are written by `POST /api/hub/auth/enter` when a member
 * follows the link, and by nothing else.
 */
export function AdminAccessi() {
  const stats = useQuery({ queryKey: ['login-stats'], queryFn: () => admin.loginStats() })
  return (
    <>
      <Header title="Accessi" count={stats.data?.totale} />
      {stats.isError ? (
        <Empty>Non riesco a leggere gli accessi.</Empty>
      ) : stats.isPending ? (
        <Empty>Caricamento…</Empty>
      ) : (
        <>
          <dl className="grid gap-4 border-b px-6 py-5 sm:grid-cols-3">
            <Figure label="Accessi" value={stats.data.totale} />
            <Figure label="Membri entrati" value={stats.data.membri} note={`su ${stats.data.membri_totali}`} />
            <Figure label="Ultimi 7 giorni" value={stats.data.ultimi_7_giorni} />
          </dl>
          {stats.data.recenti.length === 0 ? (
            <Empty>Nessun accesso ancora.</Empty>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="px-6 py-2 font-medium">Chi</th>
                  <th className="px-6 py-2 text-right font-medium">Quando</th>
                </tr>
              </thead>
              <tbody>
                {stats.data.recenti.map((login) => (
                  <tr key={login.id} className="border-b last:border-0 hover:bg-muted">
                    <td className="px-6 py-2.5">
                      <Link
                        to="/admin/freelance/$id"
                        params={{ id: login.freelancer_id }}
                        className="font-medium hover:underline"
                      >
                        {login.nome} {login.cognome}
                      </Link>
                      <p className="text-xs text-muted-foreground">{login.email}</p>
                    </td>
                    <td className="px-6 py-2.5 text-right text-muted-foreground">
                      {formatDateTime(login.logged_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </>
  )
}
