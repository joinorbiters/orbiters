/**
 * The prompts a person copies into the assistant they just connected (ORB-182): one
 * for the first conversation, one per first step. Written the way a person talks to
 * their assistant, with every value to fill in marked as «…», and naming only what the
 * MCP can do: since ORB-188 that includes the fiscal profile and the emitter
 * (`update_fiscal_profile`, `update_emitter_profile`, admin-only), so the fiscal step
 * is one imperative voice, «imposta», like the others. Every prompt asks for a summary
 * and the person's ok before anything is written.
 */
import type { StepId } from './firstSteps'

export const INTRO_PROMPT =
  'Ciao! Sei collegato al mio spazio PigroCRM. Presentati in due righe, dimmi cosa vedi nello spazio (clienti, deal, ore, documenti, il profilo fiscale) e cosa puoi fare per me. Poi proponimi i primi tre passi per partire, nell’ordine giusto, e aspetta il mio ok prima di fare qualsiasi modifica.'

export const STEP_PROMPTS: Record<StepId, string> = {
  fiscali:
    'Imposta su PigroCRM i miei dati fiscali, sia l’emittente sia il profilo fiscale. Emittente: ragione sociale «…», partita IVA «…», codice fiscale «…», indirizzo «via …, CAP, città (provincia)», PEC «…», codice SDI «…», email «…», telefono «…». Profilo fiscale: regime «forfettario» (codice «RF19»), coefficiente di redditività «78» %, imposta sostitutiva «5» %, contributi INPS «26,07» %, pagamento con «bonifico» a «30» giorni, IBAN «IT…». Prima di salvare mostrami il riepilogo completo di entrambi e chiedimi conferma. Se un dato manca, lascialo vuoto e dimmelo: non inventare niente.',
  cliente:
    'Crea su PigroCRM un nuovo cliente: «Ragione sociale S.r.l.», partita IVA «…», indirizzo «via …, CAP, città (provincia)», email «…», PEC «…», codice SDI «…». Aggiungi come referente «Nome Cognome», ruolo «…», email «…», telefono «…». Se un campo non lo sai, lascialo vuoto e dimmelo: non inventare niente.',
  lavoro:
    'Sul cliente «…» crea un deal chiamato «…», valore previsto «… €», nello stato «Offerta», con chiusura prevista il «gg/mm/aaaa». Poi registra le ore che ho già lavorato su quel deal: «gg/mm/aaaa», «2» ore, «cosa ho fatto». Alla fine dimmi il totale delle ore e il valore della pipeline aperta.',
  documento:
    'Prepara un’offerta per il deal «…» del cliente «…» usando il template «Offerta». Oggetto: «…». Ambito e obiettivi: «…». Attività: «…». Condizioni economiche: «…». Fatturazione e pagamento: «…». Mostrami l’anteprima del testo e aspetta il mio ok prima di generare il PDF.',
}
