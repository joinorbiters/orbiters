/**
 * The prompts a person copies into the assistant they just connected (ORB-182): one
 * for the first conversation, one per first step. Written the way a person talks to
 * their assistant, with every value to fill in marked as «…», and naming only what the
 * MCP can do: the emitter's identity is a deliberate exclusion of the agent surface
 * (`test_mcp_surface_coverage.py`, «identita' fiscale dell'emittente»), so the fiscal
 * prompt asks for the fiscal profile and says plainly that the emitter is typed by hand.
 */
import type { StepId } from './firstSteps'

export const INTRO_PROMPT =
  'Ciao! Sei collegato al mio spazio PigroCRM. Presentati in due righe, dimmi cosa vedi nello spazio (clienti, deal, ore, documenti, il profilo fiscale) e cosa puoi fare per me. Poi proponimi i primi tre passi per partire, nell’ordine giusto, e aspetta il mio ok prima di fare qualsiasi modifica.'

export const STEP_PROMPTS: Record<StepId, string> = {
  fiscali:
    'Imposta il mio profilo fiscale su PigroCRM. Sono in regime forfettario (codice RF19), coefficiente di redditività «78» %, imposta sostitutiva «5» %, contributi INPS «26,07» %. Pagamenti: «bonifico», scadenza a «30» giorni, IBAN «IT…». Prima di salvare mostrami un riepilogo e chiedimi conferma. Poi ricordami cosa devo compilare io a mano in Impostazioni → Emittente (ragione sociale, partita IVA o codice fiscale, indirizzo, PEC, codice SDI): quella parte non la puoi fare tu.',
  cliente:
    'Crea su PigroCRM un nuovo cliente: «Ragione sociale S.r.l.», partita IVA «…», indirizzo «via …, CAP, città (provincia)», email «…», PEC «…», codice SDI «…». Aggiungi come referente «Nome Cognome», ruolo «…», email «…», telefono «…». Se un campo non lo sai, lascialo vuoto e dimmelo: non inventare niente.',
  lavoro:
    'Sul cliente «…» crea un deal chiamato «…», valore previsto «… €», nello stato «Offerta», probabilità «50» %. Poi registra le ore che ho già lavorato su quel deal: «gg/mm/aaaa», «2» ore, «cosa ho fatto». Alla fine dimmi il totale delle ore e il valore della pipeline aperta.',
  documento:
    'Prepara un’offerta per il deal «…» del cliente «…» usando il template «Offerta». Oggetto: «…». Ambito e obiettivi: «…». Attività: «…». Condizioni economiche: «…». Fatturazione e pagamento: «…». Mostrami l’anteprima del testo e aspetta il mio ok prima di generare il PDF.',
}
