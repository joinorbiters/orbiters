import type { SendState } from './draftQueries'

/**
 * What the person is told, per state. A plain module rather than a constant inside the
 * composer: `react-refresh/only-export-components` refuses a component module that also
 * exports values, and `esito.ts` next door already established the split.
 *
 * The line that matters is `incerto`. It means **nobody knows** whether the message left,
 * and the word it must never use is «inviata»: writing "sent" for a state that means "we
 * do not know" is the exact lie this whole design exists to prevent (spec 6.3(b)), and it
 * is what Acme did -- «il CRM crede una cosa diversa da quella che è successa». It is not
 * an error state either: nothing went wrong that anybody can point at, which is precisely
 * why it needs a name of its own rather than being rounded to the nearest neighbour.
 */
export const STATE_HEADING: Record<SendState, string> = {
  bozza: 'Bozza',
  in_invio: 'Invio in corso',
  inviato: 'Inviata',
  incerto: 'Esito da verificare',
  fallito: 'Invio non riuscito',
}

/**
 * The sentence under the heading. Each one says what the person can *do*, because a state
 * label alone leaves «esito da verificare» looking like a warning to be dismissed.
 *
 * `incerto` names «Verifica» and says, in as many words, not to send it again. That is the
 * one instruction on this screen that costs a real person real money if it is missing: the
 * send has no idempotency key, so a second press is a second email in a client's inbox.
 */
export const STATE_HELP: Record<SendState, string> = {
  bozza: 'Non è ancora partita. Il testo è salvato: puoi chiudere e riprendere.',
  in_invio: 'L’invio è in corso. Attendi: non serve fare altro.',
  inviato: 'È partita. Trovi il messaggio nella conversazione qui accanto.',
  incerto:
    'Gmail non ha risposto, quindi non sappiamo se il messaggio sia partito. ' +
    'Usa «Verifica» per scoprirlo: non rinviarlo, perché potrebbe essere già arrivato.',
  fallito: 'Non è partita. Il testo è intatto: correggilo e riprova.',
}

/**
 * Whether the text promises an attachment that is not there.
 *
 * The half of the problem that can only be caught here. `SollecitiService` no longer
 * *writes* «in allegato trova copia di cortesia della fattura» when there is nothing to
 * attach -- that is settled at the source, where the answer is certain -- but nothing
 * stops a person removing the attachment afterwards, or writing «in allegato l'offerta»
 * by hand and then not attaching it. A letter to a client that promises a file and
 * carries none sends them looking for something that is not there, and a client who
 * cannot find the attachment has a reason to distrust the figure printed next to it.
 *
 * A warning and not a refusal, deliberately, and the asymmetry is the point: at the
 * template the answer is certain, so the fix is to stop promising; here the text is
 * somebody's own prose and «in allegato alla mia precedente email» is a perfectly good
 * sentence. Blocking that send would be the UI overruling a person about their own
 * words. Matching is on the phrase rather than on the reminder's exact wording, so a
 * hand-written covering email is covered by the same check.
 */
const PROMISES_AN_ATTACHMENT = /in allegato|in allegat[oi]\b|allegat[oi] a questa/i

export function promisesAnAttachmentItDoesNotHave(args: {
  body: string
  attachmentCount: number
}): boolean {
  return args.attachmentCount === 0 && PROMISES_AN_ATTACHMENT.test(args.body)
}

/** Recipients as the API wants them, from the one comma-separated field a person types.
 *  Empty entries are dropped rather than sent: a trailing comma is a typo, not a
 *  recipient, and the API would refuse the whole draft over it. */
export function parseAddresses(value: string): string[] {
  return value
    .split(',')
    .map((address) => address.trim())
    .filter((address) => address !== '')
}
