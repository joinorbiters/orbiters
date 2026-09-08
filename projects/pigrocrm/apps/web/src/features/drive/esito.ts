/**
 * The three outcome codes `GET /api/drive/oauth/callback` redirects with, rendered in
 * Italian here -- the Drive twin of `features/gmail/esito.ts`, same reasons: never
 * Google's own `error`, never a `Conflict`'s problem document, and never the raw
 * `?esito=` value echoed back (a lookup in a fixed table instead, so a crafted link
 * cannot put a sentence of its own on this page).
 */
export const ESITO_MESSAGES: Record<string, string> = {
  collegato: 'Google Drive collegato.',
  negato: 'Autorizzazione negata: Drive non è stato collegato.',
  // Deliberately says nothing about the cause. The panel below re-reads the account and
  // shows the true state -- which address is connected, and the button that disconnects
  // it -- and that is more actionable than any sentence this table could carry.
  errore:
    'Il collegamento non è andato a buon fine. Controlla qui sotto lo stato di Drive e ' +
    'riprova.',
}

export function messaggioEsito(esito: string | undefined): string | null {
  if (esito === undefined) return null
  return ESITO_MESSAGES[esito] ?? null
}
