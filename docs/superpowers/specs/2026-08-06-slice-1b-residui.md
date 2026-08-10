# Slice 1B — residui noti

**Stato:** in corso, aggiornato mentre lo slice avanza
**Scopo:** ciò che sappiamo essere aperto, con l'evidenza che lo dimostra. Ogni voce è stata
riprodotta eseguendola, non dedotta leggendo. Le voci `B*` riguardano il frontend, le voci `A*`
sono difetti del backend emersi dal frontend: appartengono allo slice 1A, che è già in `main`.

---

## A12 — `required: true` su una checkbox è soddisfacibile non facendo nulla

Il `required` del backend, per una checkbox, ha sempre significato «presente», mai «vera»:
`is_blank(False)` è `False`, quindi una casella spenta è un valore legittimo e supera il
controllo. Da quando il form manda esplicitamente `false` in creazione, una casella obbligatoria
si soddisfa ignorandola.

Oggi non fa danno perché nessuno ha definito una casella obbligatoria. Ma è esattamente la forma
che avrebbe una casella di consenso — «dichiaro di…» — e sarebbe finta.

**Da decidere:** `required` su un `checkbox` significa «rispondi» o «rispondi sì»? Sono due
prodotti diversi e solo il secondo rende utile il flag. Se è il secondo, il controllo sta in
`validate_custom_fields`, non nel client.

---

## A13 — Una chiave custom può collidere con una colonna nativa

`FieldDefinitionService.create` verifica le collisioni solo contro le altre definizioni, mai
contro `native_fields()`. Riprodotto: un campo etichettato `Email` su `customer` slugifica in
`email`, l'API risponde 201, e da lì in poi la scheda di quel cliente ha due controlli con lo
stesso `id="field-email"`, chiavi React duplicate in console, un nome accessibile impastato
(«Email Email») e una modifica che finisce silenziosamente in `custom_fields.email` invece che
nella colonna vera.

**Cura:** una guardia in `create` che confronti `slugify_key(label)` con `native_fields(entity_type)`.
Il frontend non può difendersi da solo: riceve due campi legittimi con la stessa chiave.

---

## A14 — `DealUpdate` non sa azzerare una colonna nativa numerica o di data

Riguarda `valore_previsto`, `probabilita`, `data_chiusura_prevista`, `ore_preventivate`,
`valore_preventivato`. Provate tutte le grafie possibili, dal vivo:

| si manda | risposta | effetto |
|---|---|---|
| `""` | 422 `decimal_parsing` | nessuno, valore intatto |
| `null` | 200 | **nessuno**, scartato da `exclude_none=True` prima del servizio |
| chiave omessa | 200 | nessuno |
| `"0.00"` | 200 | scrive zero, che è un valore, non il vuoto |

Non esiste una quinta grafia. L'utente che svuota il campo «Valore previsto» riceve
`Input should be a valid decimal` — in inglese grezzo, dentro una UI tutta italiana — e non ha
nessuna azione che funzioni.

La causa è di progetto, non di dettaglio: `None` significa «non fornito» dappertutto, quindi non
resta modo di dire «forniscilo vuoto». Sulle colonne di testo la stringa vuota fa da terza
grafia; sulle colonne tipizzate quella via non c'è. La cura pulita è `exclude_unset=True` con
`model_fields_set` al posto di `exclude_none=True`, che è una modifica di contratto su tutti i
servizi e merita un task suo.

---

## B1 — Nessun test automatico sulla hook con id vuoto

Su Persone, `useCustomer('')` produceva un 307 verso l'endpoint di *lista* con URL assoluto:
scavalcava perfino il proxy di Vite e chiamava il backend in diretta. Risolto rendendo
condizionale la riga invece della hook, ma senza test — nel progetto nessun file di rotta ha
test, nemmeno quelli dei clienti. Una rifattorizzazione può reintrodurlo in silenzio.

---

## B2 — La lista deal non ha debounce sulla ricerca

Ogni tasto premuto lancia `ceil(n/200)` richieste. Invisibile con poche decine di deal.

---

## B3 — La board Kanban carica anche i deal chiusi, per sempre

Vinto e Perso si accumulano e non escono più dal fetch. Con l'andare del tempo la board paga il
costo di tutta la storia commerciale per disegnare le colonne aperte.

---

## B4 — Restringere le opzioni di un `select` blocca record che nessuno sa quali siano

Da quando le definizioni di campo si possono modificare, un amministratore può togliere
un'opzione da un `select`. Ogni record che teneva l'opzione ora sparita **non è più salvabile dal
proprio form**, nemmeno modificando un campo diverso: `validate_custom_fields` rifiuta il valore
orfano con un messaggio preciso — `'Media' non è tra le opzioni ammesse (atteso: uno tra: Bassa,
Alta)`.

Il dato non si corrompe e l'errore non è muto: è la scopribilità il problema. Niente avvisa
l'amministratore, né prima né dopo il salvataggio, che sta per creare quel blocco, e non esiste
modo di sapere quali record ne siano colpiti. Ci si arriva per caso, modificando altro.

**Cura minima:** un avviso nel dialog di modifica quando si toglie un'opzione ancora in uso, con
il conteggio dei record coinvolti.

---

## B5 — `useUpdateUser` è una sola mutazione condivisa da tutte le righe

Il selettore di ruolo e l'interruttore Disattiva vivono sulla stessa istanza, quindi l'`isPending`
di una riga disabilita per un istante i controlli di tutte le altre. Dura meno di un secondo e non
tocca i dati.
