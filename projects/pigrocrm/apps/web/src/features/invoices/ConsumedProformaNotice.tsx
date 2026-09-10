import { Link } from '@tanstack/react-router'
import { formatInvoiceNumber } from './format'
import { type Invoice, useInvoices } from './queries'

/**
 * What «Consumata» means, said on the page it is said of.
 *
 * Issuing a proforma creates a new numbered row and freezes the proforma (spec 5); the
 * proforma keeps no pointer to it, the fattura points back with `origine_proforma_id`.
 * A person who lands here after «Emetti», or from the list, sees a document with no
 * actions and no XML and reads it as lost (ORB-134, Ivan on 2026-09-11: «non ci sta il
 * pulsante»). This asks the list for the one row that points here and links to it,
 * so the way to the fattura is one click from the proforma and not a search by number.
 */
export function ConsumedProformaNotice({ proforma }: { proforma: Invoice }) {
  const fatture = useInvoices({ origine_proforma_id: proforma.id, tipo: 'fattura', limit: 1 })
  const fattura = fatture.data?.items[0]
  if (fatture.isLoading) return null
  return (
    <p className="text-muted-foreground text-sm" data-testid="consumed-proforma-notice">
      {fattura ? (
        <>
          Questa proforma è stata emessa come fattura{' '}
          <Link
            to="/app/fatture/$invoiceId"
            params={{ invoiceId: fattura.id }}
            className="text-foreground font-medium underline underline-offset-4"
          >
            {formatInvoiceNumber(fattura)}
          </Link>
          : PDF e XML FatturaPA sono lì.
        </>
      ) : (
        // A consumed proforma always has its fattura; the list not answering one is a
        // network error or a race with the emission that has just happened, and the
        // sentence still says where to look.
        'Questa proforma è stata emessa: la fattura con il numero e l\u2019XML è nell\u2019elenco delle fatture.'
      )}
    </p>
  )
}
