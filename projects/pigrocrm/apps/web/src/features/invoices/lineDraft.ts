/** A row as the editor holds it: every field a string, because that is what an input
 *  gives back. The conversion to the API's shape happens once, on submit.
 *
 *  Its own module rather than living beside the editor component: eslint's
 *  `react-refresh/only-export-components` refuses a file exporting both a component and
 *  a plain function, and the brief's answer was an override in the eslint config. That
 *  trades a real guarantee for a convenience — fast refresh cannot tell which half of
 *  such a file changed, so editing `emptyLine` would remount the editor and discard
 *  whatever the user had typed into the rows. A second file costs nothing.
 */
export interface DraftLine {
  descrizione: string
  quantita: string
  unita_misura: string
  prezzo_unitario: string
  sconto_percentuale: string
  sconto_importo: string
}

export function emptyLine(): DraftLine {
  return {
    descrizione: '',
    quantita: '1',
    unita_misura: '',
    prezzo_unitario: '',
    sconto_percentuale: '',
    sconto_importo: '',
  }
}
