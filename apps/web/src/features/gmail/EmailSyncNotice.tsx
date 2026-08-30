import { useGmailSyncing } from './queries'

/**
 * What happens next to an address the user has just typed in.
 *
 * The CRM's relevance rule is the address book (`gmail/roster.py`), so adding an email
 * to a person is what makes their conversations appear -- but not at the moment of
 * saving. `GmailSyncService._run_cycle` splits the roster into addresses it has already
 * searched, which are read from the watermark, and fresh ones, which are read back over
 * `gmail_backfill_days`; the fresh ones are only recorded as seen after that pass
 * succeeds. So a new address is picked up by the *next* cycle, with its history behind
 * it. That is a good behaviour and a surprising one, and the cheapest place to say so
 * is next to the field that causes it.
 *
 * It says nothing at all unless a cycle is genuinely going to run. With no mailbox
 * connected, or a revoked consent, or a credential that never got `gmail.readonly`,
 * "al prossimo sync" describes an event that will not happen -- and a promise the
 * product cannot keep is worse than no sentence, because the user has no way to find
 * out it was empty except by waiting.
 *
 * Its own module rather than a helper inside `PersonForm`: the customer form has the
 * same email field and the same future, so the sentence should be reachable from there
 * without being copied.
 */
export function EmailSyncNotice() {
  const syncing = useGmailSyncing()
  if (!syncing) return null

  return (
    <p className="text-sm text-muted-foreground">
      Le conversazioni con questo indirizzo compariranno al prossimo sync di Gmail, non
      immediatamente.
    </p>
  )
}
