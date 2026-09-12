/**
 * The prompts a person copies into the assistant they just connected (ORB-182): one
 * for the first conversation, one per first step. Written the way a person talks to
 * their assistant, with every value to fill in marked as «…», and naming only what the
 * MCP can do in this space: the emitter's identity is a deliberate exclusion of the agent
 * surface (`test_mcp_surface_coverage.py`, «identita' fiscale dell'emittente»), and
 * `update_fiscal_profile` is registered only where the space grants the agent full access
 * (`mcp_full_access`, off by default). So the fiscal prompt has two voices: read and
 * explain by default, write the whole profile where the switch is on; both say plainly
 * that the emitter is typed by hand.
 */
import type { StepId } from './firstSteps'

export const INTRO_PROMPT =
  'Ciao! Sei collegato al mio spazio PigroCRM. Presentati in due righe, dimmi cosa vedi nello spazio (clienti, deal, ore, documenti, il profilo fiscale) e cosa puoi fare per me. Poi proponimi i primi tre passi per partire, nell’ordine giusto, e aspetta il mio ok prima di fare qualsiasi modifica.'

/** The fiscal step where the agent may only read (the default of every space). */
const FISCAL_PROMPT_READ =
  'Leggi il mio profilo fiscale su PigroCRM e dimmi com’è impostato: regime, coefficiente di redditività, imposta sostitutiva, contributi INPS, modalità e scadenza di pagamento, IBAN. Io sono in regime «forfettario», coefficiente «78» %, imposta «5» %, INPS «26,07» %, pagamento «bonifico» a «30» giorni, IBAN «IT…»: dimmi cosa non corrisponde e cosa devo cambiare io in Impostazioni → Fiscale. Poi ricordami cosa devo compilare a mano in Impostazioni → Emittente (ragione sociale, partita IVA o codice fiscale, indirizzo, PEC, codice SDI): quella parte non la puoi fare tu.'

/** The fiscal step where the space grants the agent full access: it writes the whole
 *  profile, so the summary is of the whole profile, not only of the values named. */
export const FISCAL_PROMPT_FULL_ACCESS =
  'Imposta il mio profilo fiscale su PigroCRM. Regime «forfettario» (codice «RF19»), coefficiente di redditività «78» %, imposta sostitutiva «5» %, contributi INPS «26,07» %. Pagamenti: «bonifico», scadenza a «30» giorni, IBAN «IT…». Prima di salvare mostrami un riepilogo dell’intero profilo, anche dei campi che non ti ho dato, e chiedimi conferma. Poi ricordami cosa devo compilare io a mano in Impostazioni → Emittente (ragione sociale, partita IVA o codice fiscale, indirizzo, PEC, codice SDI): quella parte non la puoi fare tu.'

export const STEP_PROMPTS: Record<StepId, string> = {
  fiscali: FISCAL_PROMPT_READ,
  cliente:
    'Crea su PigroCRM un nuovo cliente: «Ragione sociale S.r.l.», partita IVA «…», indirizzo «via …, CAP, città (provincia)», email «…», PEC «…», codice SDI «…». Aggiungi come referente «Nome Cognome», ruolo «…», email «…», telefono «…». Se un campo non lo sai, lascialo vuoto e dimmelo: non inventare niente.',
  lavoro:
    'Sul cliente «…» crea un deal chiamato «…», valore previsto «… €», nello stato «Offerta», con chiusura prevista il «gg/mm/aaaa». Poi registra le ore che ho già lavorato su quel deal: «gg/mm/aaaa», «2» ore, «cosa ho fatto». Alla fine dimmi il totale delle ore e il valore della pipeline aperta.',
  documento:
    'Prepara un’offerta per il deal «…» del cliente «…» usando il template «Offerta». Oggetto: «…». Ambito e obiettivi: «…». Attività: «…». Condizioni economiche: «…». Fatturazione e pagamento: «…». Mostrami l’anteprima del testo e aspetta il mio ok prima di generare il PDF.',
}

/** The prompt for a step, in the voice the space allows: the fiscal one writes only
 *  where the agent has full access. */
export function promptFor(id: StepId, { fullAccess }: { fullAccess: boolean }): string {
  return id === 'fiscali' && fullAccess ? FISCAL_PROMPT_FULL_ACCESS : STEP_PROMPTS[id]
}
