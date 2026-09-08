# PigroCRM — Slice 4: Time tracking, costi, P&L e preventivo vs consuntivo

**Data:** 2026-08-20
**Stato:** da approvare
**Prerequisiti:** slice 1 (Core CRM + MCP) in `main`; slice 2 (Documenti e template) con motore
`{{}}`, `escape_for`, `documents`/`document_versions`, `templates` ed `emitter_profile`; slice 3
(Fatturazione) in `main` **per la parte 4B soltanto** (§16).

**Ambito:** registrazione delle ore, costi con categorie configurabili, tariffe di vendita e costi
interni congelati per riga, conto economico per deal e per periodo, confronto preventivo vs
consuntivo, rapporto ore in PDF e XLSX, calcolo fiscale di periodo.

---

## 1. Perché questo slice esiste

Il brief originale lo dice senza mezzi termini: per chi vende servizi, **il margine per progetto è
probabilmente il KPI più importante che esista**. Un CRM che sa quanto hai preventivato e quanto hai
fatturato, ma non quante ore ci hai messo, sa dire quanto hai incassato e non sa dire se ne valeva la
pena. È la differenza fra un archivio commerciale e uno strumento di decisione.

Il ciclo dichiarato nello slice 1 — *Contatto → Cliente → Deal → Offerta → Lavoro → Time Tracking →
Fattura → Analisi economica* — ha oggi tutti gli anelli tranne il sesto e l'ottavo. Questo slice li
chiude, e li chiude nell'ordine giusto: le ore prima, l'analisi dopo, perché l'analisi senza le ore è
una divisione per zero.

È anche il momento in cui si riscuote un investimento fatto in anticipo. `deals.ore_preventivate` e
`deals.valore_preventivato` esistono dallo slice 1 (`deals/models.py`, con il commento che lo dice
esplicitamente: *«written now, consumed by the slice 4 estimate-vs-actual report»*) e non sono mai
stati letti da nessuno. Il frontend li conosce già: `apps/web/src/features/deals/columns.tsx` li
esclude deliberatamente dalle colonne di tabella «until the slice 4 estimate-vs-actual report», e la
scheda deal ha già una card «Preventivo». Il consuntivo è l'unica metà mancante.

E infine: questo slice ospita l'ultimo pezzo di logica di the previous system che vive ancora nel browser. Lo slice
1 §2.2 cita come giustificazione empirica dell'intera architettura tre costanti dentro `App.jsx`
(`FORFETTARIO_INPS_RATE = 0.2607`, coefficiente 67%, sostitutiva 5%). Sono lì per calcolare un
margine. Portarle in `packages/core` è il pagamento finale di quel debito.

---

## 2. Cosa si porta da the previous system, e cosa si riscrive

Il precedente è quello degli slice 2 e 3: **il contenuto guadagnato sul campo si porta, il
meccanismo che lo eseguiva no.** Nello slice 3 quella lettura ha trovato tre bug vivi in codice che
girava in produzione; qui ne ha trovati sette, elencati al §2.2 con la riga che li dimostra.

Le fonti lette per intero: `the reference copy/website/vite.config.js` righe 1076-1265 (modello e
persistenza delle voci), 3171-3362 (API `/api/time-tracking`), `the reference copy/offer/template-time-tracking.typ`,
e `the reference copy/website/src/App.jsx` righe 1783-1963 (la vista `project-costs`, che è il P&L di
the previous system).

### 2.1 Portato

| Elemento | Perché è conoscenza, non codice |
|---|---|
| **Layout del rapporto ore** (`template-time-tracking.typ`): testata con identità emittente a destra e logo a sinistra, riga «Periodo / Data emissione», blocco Cliente + Offerta, tabella a tre colonne `DATA · ORE · DESCRIZIONE` con la colonna descrizione a `0.7fr`, divisore, piede con **totale ore e numero di voci** | È un documento mandato a clienti veri per anni. Le proporzioni delle colonne sono state tarate dall'uso: la descrizione è il 70% della larghezza perché è l'unica colonna che il cliente legge davvero. Il conteggio delle voci accanto al totale ore è il dettaglio che rende il documento verificabile a occhio |
| **Forma del foglio XLSX** (`buildTimeTrackingXlsx`, `vite.config.js:1204-1256`): blocco di testata su quattro righe (titolo, Cliente, Offerta, Periodo) con celle unite, riga 5 di intestazione in grassetto su fondo grigio, **riquadro congelato a `ySplit: 5`**, larghezze `14 / 10 / 80`, formato `dd/mm/yyyy` sulla data e `0.00` sulle ore, `wrapText` sulla descrizione, riga finale «Totale ore» in grassetto | Chi riceve un timesheet lo apre, scorre e filtra. Il riquadro congelato e la larghezza 80 sulla descrizione sono ciò che rende il file usabile invece che soltanto corretto — e non sono deducibili da nessuna specifica |
| **Il periodo come chiave `AAAA-MM`** e l'etichetta in italiano lungo («marzo 2026») | Il taglio mensile è quello che il cliente si aspetta accanto a una fattura, ed è quello su cui si concorda |
| **L'esistenza di due formati per lo stesso dato** — PDF per il cliente, XLSX per chi deve ricontrollare | Non è ridondanza: sono due destinatari con due esigenze. Il PDF si allega alla fattura, l'XLSX si filtra |
| **Il costo come entità propria con allegato** (`readPassiveList`, `vite.config.js:1033-1065`: descrizione, data, importo, fornitore implicito, allegato) | Il giustificativo attaccato al costo è la ragione per cui il costo è credibile a distanza di un anno. Diventa un `document_id` (slice 2), non un base64 in un file JSON |

### 2.2 Riscritto, e perché

Ogni voce è un difetto **letto nel sorgente di riferimento**, non un miglioramento ipotetico.

| Difetto | Cosa cambia |
|---|---|
| **La voce di time tracking è legata all'offerta da tre stringhe libere** (`offerId`, `offerFileName`, `offerName`) e `matchOffer` accetta la corrispondenza di *una qualsiasi* delle tre (`vite.config.js:1155-1160`). Rinominare un'offerta scollega le ore già registrate contro il nome | Una FK `deal_id` verso `deals`, obbligatoria e vincolata dal database. Non esiste una seconda via per collegare un'ora a un lavoro |
| **Le somme del P&L perdono righe, in silenzio.** `App.jsx:1838-1842` fa `hoursByOfferKey.get(offer.id) \|\| hoursByOfferKey.get(offer.fileName) \|\| hoursByOfferKey.get(offer.offerName) \|\| 0` — prende il **primo** secchiello non vuoto, non la loro somma. Ore registrate contro il nome dell'offerta spariscono se anche una sola ora è stata registrata contro il suo id. Identico su `linkedExpenseMap` (righe 1836-1838): un costo collegato per nome a un'offerta risolta per id **non entra nel margine**, e nessuno se ne accorge | Con una FK sola non esistono secchielli da fondere. La somma è un `GROUP BY deal_id` |
| **`description` viene escapata per Typst al momento della scrittura** e memorizzata già escapata: `normalizeSingleLine` (riga 79) applica `escapeTypstText`, che protegge `\ @ # [ ]`. La stringa escapata finisce **tale e quale nella cella XLSX** (`vite.config.js:1245`) e viene **escapata una seconda volta** da `escapeTypstString` nel PDF (riga 1181). Una descrizione «Call con @mario su [fase 1]» è archiviata come `Call con \@mario su \[fase 1\]` e arriva così al cliente nel foglio Excel | È il difetto che lo slice 3 §2.2 ha già diagnosticato sull'XML, qui sul terzo e quarto bersaglio. **L'escaping si applica sempre al valore di dominio, mai a un valore già preparato per un altro bersaglio**: il valore è archiviato grezzo, e `escape_for` (slice 2) lo prepara al render. Nessun valore attraversa due escaper, e l'XLSX non ne attraversa nessuno |
| **`normalizeSingleLine` tiene solo la prima riga**: `String(value).split(/\r?\n/)[0]`. Una descrizione su tre righe perde due righe senza errore | La descrizione è `Text` e conserva gli a capo. Il render li gestisce nel contesto di destinazione, che è il posto in cui esiste il problema |
| **Persistenza read-then-write sull'intero archivio, senza lock**: `readTimeTrackingList()` → `push` → `writeTimeTrackingList(entries)` (`vite.config.js:3219-3222`). Due registrazioni concorrenti ne perdono una; una `DELETE` riscrive tutto il file (riga 3352) e un'interruzione a metà scrittura tronca l'intero storico | Postgres, una riga per voce. È lo stesso difetto che lo slice 3 §2.2 ha trovato su `getNextInvoiceProgressive`: non è una coincidenza, è la conseguenza di aver scelto file JSON come archivio |
| **`formatIsoDate` usa `toISOString()`, cioè UTC** (riga 123), e `normalizeTimeTrackingEntry` la applica alla data della voce. Un'ora registrata il 31 marzo alle 23:30 CEST è archiviata al 1° aprile — **e finisce nell'export mensile sbagliato**, che è esattamente il file allegato a una fattura | La data di una voce è una `date` nel fuso dell'emittente, non la proiezione UTC di un istante. Stessa regola dello slice 3 §6.2, stessa causa, un documento diverso |
| **Le ore sono float**: `parseAmount` (riga 410) produce un `Number`, i totali si accumulano con `sum + entry.hours` (righe 1172-1175, 1240, 1912). Il totale stampato sul PDF è una somma binaria arrotondata alla fine | `Numeric(8,2)` in Postgres, `Decimal` nel servizio, somma di valori già arrotondati (§6). Sul frontend, somma in centesimi interi: il progetto ha già `centsFromDecimalString` in `apps/web/src/features/deals/columns.tsx` proprio per questo |
| **La `DELETE` è fisica** (riga 3352), anche su ore già fatturate | Soft delete come tutto il resto, e un `CHECK` che rende impossibile cancellare un'ora legata a una fattura emessa (§4.3) |
| **Nessun utente sulla voce.** Non esiste alcun campo che dica chi ha lavorato | `user_id` obbligatorio (§4.1). Senza, non esiste costo del lavoro, e la domanda «quanto mi è costato» non ha risposta |
| **Nessuna tariffa, da nessuna parte.** Il ricavo del P&L è `offer.totalAmount`, cioè **l'importo dell'offerta**, filtrato ai soli progetti che hanno almeno una fattura non provvisoria (`App.jsx:1808-1825`). Un lavoro fatturato per un terzo compare a ricavo pieno | Il ricavo è ciò che è stato fatturato, letto dalle fatture (§7). E l'ora ha una tariffa e un costo, congelati sulla riga (§5) |
| **I costi di un progetto non ancora fatturato non compaiono in nessun totale**: `projectCostRows` parte da `offers.filter(offerKeysWithInvoices.has(...))`. Le spese di un lavoro in corso sono invisibili al riepilogo | Ogni deal ha il suo conto economico, fatturato o no, con lo **stato** accanto invece che con l'esclusione (§7.3) |
| **La fiscalità personale è dentro il margine di progetto**: `net = gross − substituteTax − inps`, con INPS ripartita pro-rata sul ricavo del singolo progetto (`App.jsx:1830-1845`) | §8. È sbagliato in tre modi indipendenti, e la cura non è correggere il calcolo ma toglierlo da lì |
| **`PUT` non sa svuotare un campo**: `body.offerName \|\| target.offerName \|\| ''` (riga 3243). Un valore inserito per errore non ha nessuna grafia che lo tolga | Stessa famiglia del residuo A14, e qui diventa un difetto di correttezza, non di comodità (§12) |
| **L'unica via per annullare una voce sbagliata è la cancellazione fisica.** `hours <= 0` è rifiutato — correttamente: una voce da zero ore non è una voce — ma l'unica alternativa è `DELETE`, che rimuove la riga dal file. Non è il rifiuto dello zero il difetto, è che dall'altra parte non ci sia niente | `ore > 0` resta la regola (§4.1), e l'annullamento è un **soft delete reversibile** come per ogni altra entità dello slice 1 §5.9. La correzione ha una via, e non è distruttiva |
| **Id generato client-side con `Date.now()` + 6 caratteri casuali** (riga 1076) | UUID v7, come ogni altra riga di questo schema |
| **Una voce senza offerta è invisibile a ogni export** — `filterTimeEntriesForExport` richiede una corrispondenza — **ma conta nei totali a schermo**, dove `timeTrackingSummaryRows` ripiega su `entry.id` come chiave di gruppo (`App.jsx:1893-1898`). Esistono ore che nessun documento mostrerà mai | `deal_id` obbligatorio: lo stato «ora senza lavoro» non è rappresentabile |

**`exceljs` non si porta.** Era una libreria JavaScript dentro un dev server Node che questo prodotto
non ha più. L'equivalente è `openpyxl` nell'immagine dell'API, dove Pandoc e Typst già vivono. Si
porta la **forma del foglio**, non il codice che la produceva (§10.2).

---

## 3. Le tre decisioni che reggono lo slice

Prima del modello dati, perché il modello dati è la loro conseguenza.

1. **La tariffa si congela sulla riga.** Un'ora porta con sé la tariffa di vendita e il costo interno
   che valevano nel momento in cui è stata registrata. Nessun report li ricalcola mai. È la stessa
   forma di `invoices.snapshot` dello slice 3 §8.3, applicata all'unità più piccola. (§5)
2. **Il ricavo è la fattura.** Non esiste un secondo concetto di ricavo in questo slice. Il valore
   derivato da ore × tariffa è una **stima** finché non c'è una fattura; dal momento in cui c'è, il
   ricavo è l'imponibile della fattura e la stima non viene più consultata. (§7.1)
3. **Il deal è l'unità del conto economico.** Il P&L di un cliente è la somma di quelli dei suoi
   deal; quello di un periodo è la somma dei deal più le spese generali, che **non vengono ripartite
   su nessuno**. (§7.4)

---

## 4. Modello dati

Tutti gli importi sono `Numeric(12,2)`, le ore `Numeric(8,2)`, i **fattori** (tariffe e costi orari)
`Numeric(12,6)` — §6 spiega perché il terzo tipo esiste. Tutte le tabelle hanno `id` UUID v7,
`created_at`, `updated_at` e i timestamp in UTC, come da slice 1 §5.

### 4.1 `time_entries`

| Colonna | Tipo | Note |
|---|---|---|
| `deal_id` | UUID FK `deals` | **obbligatorio**, indicizzato |
| `user_id` | UUID FK `users` | **obbligatorio** |
| `data` | Date | non timestamp: §6.3 |
| `ore` | Numeric(8,2) | `> 0` e `<= 24`, §4.1 |
| `descrizione` | Text (`SafeStr`) | obbligatoria |
| `fatturabile` | bool, default `true` | |
| `tariffa_applicata` | Numeric(12,6) null | congelata alla scrittura, §5 |
| `costo_applicato` | Numeric(12,6) null | congelato alla scrittura, §5 |
| `tariffa_origine`, `costo_origine` | String(10) null | `manuale` \| `deal` \| `utente` \| `assente` |
| `invoice_line_id` | UUID FK `invoice_lines` null | `ON DELETE SET NULL`, §9.2 |
| `note_interne` | Text null | mutabile sempre |
| `custom_fields` | JSONB | `entity_type = 'time_entry'` |
| `deleted_at` | timestamptz null | con il `CHECK` del §4.3 |

Indici: `(deal_id, data)` e `(user_id, data)`, entrambi parziali su `deleted_at IS NULL` — è la forma
che ogni query di questo slice ha, ed è la cura che il residuo R7 chiede in generale.

**`deal_id` è obbligatorio.** Il budget vive sul deal (`ore_preventivate`, `valore_preventivato`), il
ricavo arriva dalle fatture che hanno un `deal_id`, e il P&L è per deal. Un'ora agganciata solo a un
cliente non avrebbe nessun preventivo contro cui confrontarsi e sfuggirebbe a ogni riga di questo
slice; un'ora agganciata a niente è la voce fantasma che the previous system produce e che nessun export mostra
(§2.2). Il lavoro interno non riferibile a un cliente resta fuori ambito (§13): tenerlo dentro
significherebbe payroll, e payroll non è questo prodotto.

**`user_id` è obbligatorio.** Senza, non esiste costo del lavoro e metà del margine è indefinita. Non
è nullable neppure per il caso «l'ho registrata via MCP»: un `Actor` di tipo `mcp` porta l'`id`
dell'utente proprietario del PAT (slice 1 §9), quindi c'è sempre una persona a cui attribuirla.

**`ore <= 24`.** Non è un limite di produttività, è un controllo di forma: una giornata ha 24 ore, e
un valore superiore è quasi sempre lo scivolone di virgola che scrive `80` invece di `8,0` — che
senza il limite entrerebbe nel margine come diecimila euro di lavoro mai fatto. Il totale *di una
giornata* non è invece vincolato: due voci da 14 ore sullo stesso giorno sono un errore probabile ma
non impossibile, e rifiutare la seconda significherebbe rifiutare una correzione in corso.

**`fatturabile` e `invoice_line_id` sono due colonne perché rispondono a due domande.**
`fatturabile` è una proprietà del **lavoro**: la riunione di allineamento interna non si fattura
mai, e lo si decide quando la si registra. `invoice_line_id` è un fatto su un **documento**:
esiste o no una riga di fattura che la comprende. Un'ora fatturabile e non ancora fatturata è lo
stato normale di tutto ciò che è stato fatto questo mese; un'ora non fatturabile non arriverà mai ad
avere una riga. Fonderle in una colonna sola renderebbe impossibile la domanda che serve tutte le
settimane — *quanto ho da fatturare?* — perché non si distinguerebbe «non ancora» da «mai».

### 4.2 `cost_categories` e `costs`

`cost_categories` è configurabile da UI, come gli stage di pipeline e le definizioni di campo:

`nome` (String(60)) · `posizione` (Integer) · `code` (String(30) null, unique) · `archiviata` (bool)

Copia due lezioni già pagate. `code` è l'identità stabile delle categorie di seed, distinta dal nome
che l'utente è libero di rinominare — è esattamente la ragione per cui `pipeline_stages.code` è stata
aggiunta durante la review dello slice 1 (residuo R11) dopo che `seed_defaults` deduplicava su
`nome`. `archiviata` invece di cancellabile è la prima delle tre regole dello slice 1 §5.6: una
categoria cancellata con costi ancora appesi produce righe orfane invisibili. Seed:
`Consulenza esterna` · `Software e licenze` · `Viaggi e trasferte` · `Materiali` · `Altro`.

`costs`:

| Colonna | Tipo | Note |
|---|---|---|
| `deal_id` | UUID FK null | `NULL` = spesa generale, §7.4 |
| `category_id` | UUID FK `cost_categories` | obbligatorio |
| `data` | Date | |
| `importo` | Numeric(12,2) | `<> 0`; negativo ammesso, §4.4 |
| `descrizione` | Text (`SafeStr`) | obbligatoria |
| `fornitore` | String(200) null | |
| `document_id` | UUID FK `documents` null | il giustificativo, §10.3 |
| `custom_fields` | JSONB | `entity_type = 'cost'` |
| `deleted_at` | timestamptz null | soft delete ordinario |

**Perché un costo non è una voce di ore, se entrambi riducono il margine.** Tre differenze, e sono
quelle che contano:

- Un costo è **denaro uscito davvero** verso qualcun altro, e ha un giustificativo che lo dimostra.
  Il costo di un'ora è una cifra **interna e nozionale**, derivata da una tariffa che hai scelto tu:
  non compare in nessun estratto conto e nessuno te la può contestare.
- Un'ora è anche **potenziale ricavo** — può essere fatturata. Un costo non lo è mai.
- Un'ora ha una **dimensione quantitativa** confrontabile con un preventivo (`ore_preventivate`). Un
  costo ha solo denaro.

Unirle in una tabella sola di «eventi che riducono il margine» renderebbe metà delle colonne nulle su
ogni riga e trasformerebbe «ore consuntivate» — la grandezza centrale dello slice — in
un'aggregazione filtrata su una tabella dove la maggior parte delle righe non sono ore.

**Sì, un'ora ha un costo oltre che un prezzo.** Senza `costo_applicato`, un deal servito da tre
persone con costi interni diversi mostra lo stesso margine di uno servito solo dalla più economica, e
la funzionalità risponde alla domanda sbagliata. Il costo del lavoro **non genera mai una riga in
`costs`** e non è mai contato due volte: al §7.2 è una riga distinta del conto economico, e il §14
criterio 4 lo verifica.

### 4.3 Immutabilità

Un'ora legata a una riga di una fattura **emessa** è parte di un documento fiscale: non è più un dato
di CRM. La regola si aggancia allo **stato della fattura**, non alla semplice presenza del legame,
perché una bozza si modifica ancora liberamente (§9.2).

| Campo | Se `invoice_line_id` punta a una riga di una fattura `emessa` |
|---|---|
| `ore`, `data`, `tariffa_applicata`, `descrizione`, `deal_id`, `fatturabile` | **congelati** → `ImmutableField` |
| `costo_applicato` | **congelato**: è dentro il margine di un periodo già chiuso e riportato |
| `note_interne`, `custom_fields` | mutabili: non compaiono su nessun artefatto |
| `deleted_at` | **impossibile** |

```sql
ALTER TABLE time_entries ADD CONSTRAINT ck_time_entries_billed_not_deleted
  CHECK (deleted_at IS NULL OR invoice_line_id IS NULL);
```

Il `CHECK` copre il caso più grave — la sparizione — al livello in cui nessuna via di scrittura lo
può aggirare, com'è già per `invoices.deleted_at` nello slice 3 §4. Il congelamento dei singoli campi
resta nel servizio, perché dipende dallo stato di un'altra tabella e un `CHECK` non può leggerlo.

**Il `CHECK` è deliberatamente più largo della regola sopra**, e la differenza va capita: vieta la
cancellazione di *qualunque* voce legata a una riga, anche di una semplice bozza. Non è una svista ed
è raggiungibile senza attriti — per cancellare una voce ancora in bozza la si toglie prima dalla
bozza, e `invoice_line_id` torna `NULL`. Un vincolo che dovesse distinguere lo stato della fattura
avrebbe bisogno di leggere un'altra tabella, cioè di un trigger; e un trigger è precisamente il tipo
di logica invisibile che questo progetto tiene fuori dal database, dove il `CHECK` di
`invoices.deleted_at` è invece una condizione su colonne della stessa riga.

`descrizione` è fra i campi congelati e non è ovvio: è la colonna che il cliente legge nel rapporto
ore allegato alla fattura. Modificarla dopo l'emissione significa che il documento consegnato e il
database dicono due cose diverse.

**Chiudere un deal non blocca nulla.** Registrare ore su un deal in stage `won` o `lost` resta
permesso, sempre. Su un deal vinto il lavoro **comincia** in quel momento, ed è lì che si accumulano
le ore che interessano davvero; su un deal perso le ore di prevendita sono un costo reale che va
contato. Rifiutare costringerebbe a riaprire il deal per poter dire la verità, cioè a corrompere la
pipeline per salvare il consuntivo. L'interfaccia avvisa e il servizio scrive un'activity
`time_logged_on_closed_deal`; non rifiuta.

### 4.4 Il segno di un importo

`costs.importo` ammette valori negativi, che significano un rimborso o una nota di credito ricevuta.
È la stessa scelta dello slice 3 §6.1 regola 6 («uno sconto è una riga»): rappresentare la
correzione con lo strumento che c'è già, invece di aggiungere un `tipo` che moltiplica i casi in ogni
somma. Lo zero è rifiutato, perché non è né un costo né una correzione.

**L'IVA sugli acquisti è dentro `importo`.** In regime forfettario l'IVA pagata sugli acquisti non è
detraibile: è costo a tutti gli effetti, e registrare l'imponibile invece del totale sottostimerebbe
il costo del 22%. `importo` è quindi **il totale pagato**. In un regime ordinario la scelta giusta
sarebbe l'opposta, e la via di estensione è una seconda colonna `importo_iva` letta in base a
`fiscal_profile.codice_regime` — nominata qui come confine, non progettata (§13).

### 4.5 Nuove colonne su tabelle esistenti

| Tabella | Colonna | Tipo |
|---|---|---|
| `deals` | `tariffa_oraria` | Numeric(12,6) null |
| `users` | `tariffa_oraria_default` | Numeric(12,6) null |
| `users` | `costo_orario_default` | Numeric(12,6) null |
| `fiscal_profile` | `coefficiente_redditivita` | Numeric(5,2) null |
| `fiscal_profile` | `aliquota_imposta_sostitutiva` | Numeric(5,2) null |
| `fiscal_profile` | `aliquota_inps` | Numeric(5,2) null |

Le tre colonne su `fiscal_profile` **non** sono una seconda tabella. Lo slice 1 §3 descriveva un
`FiscalProfile` che contenesse «regime, coefficiente ATECO, aliquota sostitutiva, INPS/cassa»; la
tabella consegnata dallo slice 3 §7.1 contiene i parametri che servivano alla FatturaPA e non quelli
che servono al calcolo del reddito, che nessuno usava ancora. Sono lo stesso concetto, quindi vanno
sulla stessa riga singola: un secondo profilo fiscale creerebbe due risposte alla domanda «in che
regime sono». Default dal profilo attuale di the previous system: `67.00`, `5.00`, `26.07`.

Come per lo slice 3 §7.1, **ogni modifica a queste colonne e alle tariffe scrive un'activity**. Il
residuo R5 resta aperto in generale; qui si chiude per le tabelle che questo slice tocca, e non per
igiene: è la timeline che ricostruisce quando una tariffa è cambiata, ed è la ragione per cui il §5
può permettersi di non storicizzarle.

### 4.6 `entity_type`

`time_entry` e `cost` si aggiungono ai valori ammessi. Il residuo R13 dice esattamente quanto costa,
e va ripetuto nella forma corretta invece che nella promessa smentita tre volte: **il database è
aperto** (`String(30)` senza vincolo), **il tipo va esteso in quattro punti** —
`fields/schemas.py:EntityType`, `schema_registry.py:ENTITY_TYPES` e `CREATE_MODELS`,
`apps/web/src/lib/schema.ts:EntityType` — **e nessuna migrazione serve**.

`native_fields()` è derivata dal modello Pydantic e non da un elenco a mano, quindi si aggiorna da
sola. Ma qui il residuo **A13** smette di essere teorico: `FieldDefinitionService.create` non
confronta lo slug con `native_fields()`, e le colonne native di questo slice si chiamano `ore`,
`data`, `importo`, `descrizione` — cioè esattamente le etichette che un utente scriverebbe per primo
definendo un campo custom su una voce di ore. Un campo etichettato «Ore» su `time_entry` slugifica in
`ore`, l'API risponde 201, e da lì in poi la modifica finisce in `custom_fields.ore` invece che nella
colonna vera, senza che nessuno protesti. **Questo slice implementa la guardia** (`slugify_key(label)`
confrontato con `native_fields(entity_type)` in `create`), chiudendo A13 come effetto collaterale
necessario, non come cortesia.

---

## 5. Le tariffe — dove questa funzionalità di solito marcisce

Un'ora ha due numeri: quanto la vendi e quanto ti costa. Entrambi cambiano nel tempo. La domanda che
decide se il prodotto è affidabile è: **cosa succede al margine del trimestre scorso quando alzi la
tariffa oggi?**

La risposta di questo slice è: **niente, e non per disciplina ma per costruzione.**

### 5.1 Risoluzione, una volta sola, alla scrittura

Alla creazione di una voce, il servizio risolve tariffa e costo nell'ordine, e si ferma al primo che
dà un valore:

| Ordine | Tariffa di vendita | Costo interno | `origine` |
|---|---|---|---|
| 1 | valore esplicito nella richiesta | valore esplicito nella richiesta | `manuale` |
| 2 | `deals.tariffa_oraria` | — | `deal` |
| 3 | `users.tariffa_oraria_default` | `users.costo_orario_default` | `utente` |
| 4 | nessuno → `NULL` | nessuno → `NULL` | `assente` |

Il valore risolto viene **copiato sulla riga** in `tariffa_applicata` / `costo_applicato`, insieme
all'origine. Da quel momento nessun report legge più `deals.tariffa_oraria` né
`users.tariffa_oraria_default`: legge la copia.

Il costo interno non ha un livello «deal» perché non ne ha bisogno: il costo di un'ora è una proprietà
di chi la lavora, non del cliente per cui la lavora. Aggiungere il livello significherebbe permettere
di dichiarare che la stessa persona costa diversamente su due progetti, che è una scrittura contabile,
non un dato di CRM. La conseguenza da leggere nella tabella: **`costo_origine` non assume mai il
valore `deal`** — i suoi valori possibili sono `manuale`, `utente`, `assente`.

**Non c'è un livello «tariffa di questa persona su questo deal».** È il quarto livello che ogni
sistema di questo tipo finisce per avere, e resta fuori perché oggi non ha esercitatori: il
destinatario è un freelance o uno studio di poche persone, dove la tariffa la decide il contratto col
cliente (livello `deal`) e l'eccezione la si scrive sulla singola voce (livello `manuale`). La via di
estensione, se servirà, è una tabella `deal_user_rates(deal_id, user_id, tariffa)` inserita fra i
livelli 1 e 2: nessuna colonna nuova sulle tabelle esistenti, e il congelamento del §5.1 la rende
invisibile a tutti i dati già scritti.

**Nessun default globale, e nessun ripiego a zero.** Se nessun livello risolve, `tariffa_applicata`
resta `NULL` e la voce è registrata lo stesso. Nel P&L quelle ore compaiono nel conteggio ore, sono
**escluse** dal valore maturato e dal margine, e sono nominate a schermo come «ore senza tariffa» con
il loro numero. Un ripiego silenzioso a `0.00` direbbe «questo lavoro è stato gratis», che è una
bugia che somma; un default globale sarebbe un numero che nessuno ha scelto e che diventa in silenzio
la tariffa di tutti.

### 5.2 Perché non una tabella storicizzata

`rate_history(user_id, valido_da, valido_a, tariffa)` è stata considerata e scartata. Tre ragioni,
tutte verificabili:

1. **Non elimina la copia, la duplica.** Anche con una storia delle tariffe, una voce **retrodatata**
   scritta oggi leggerebbe la tariffa del periodo di allora e cambierebbe un totale che qualcuno ha
   già letto. Per impedirlo servirebbe comunque congelare il valore sulla riga — e a quel punto la
   tabella storica è un secondo posto in cui la stessa verità può divergere.
2. **Trasforma ogni lettura in una join temporale.** Il margine di un periodo diventa una query che
   dipende da intervalli di validità modificabili: cambiare un `valido_da` per correggere un errore
   di inserimento riscrive i margini di tutti i periodi coperti, silenziosamente. Con la copia sulla
   riga, il margine è una somma.
3. **La domanda a cui servirebbe ha già una risposta migliore.** «Quando è cambiata la tariffa di
   Marco?» la risponde la timeline (§4.5), che è anche l'unico posto che dice *chi* l'ha cambiata. È
   lo stesso ragionamento con cui lo slice 3 §7.1 ha rifiutato di storicizzare `fiscal_profile`.

È la stessa forma di `invoices.snapshot`: **la riga è l'autorità su sé stessa, sempre e solo**, e non
può divergere dalla configurazione perché non la consulta.

### 5.3 L'unica via per cambiare il passato, ed è visibile

Un errore vero esiste: si è digitato 80 invece di 180 e ci si accorge dopo due settimane. Negarlo
produrrebbe correzioni fatte a mano riga per riga, che è peggio.

`TimeEntryService.recalculate_rates(deal_id, da, a, actor)`:

- richiede ruolo **`admin`**;
- **rifiuta con `Conflict`** se l'intervallo contiene anche una sola voce legata a una riga di
  fattura **emessa**, nominando quante sono e la prima fattura coinvolta — perché quel numero è già
  stato consegnato a un cliente;
- ricalcola tariffa e costo delle voci restanti con la risoluzione del §5.1 e le riscrive;
- scrive **un'activity per voce**, con valore vecchio e valore nuovo;
- **non esiste come tool MCP** (§11).

Non è disponibile via MCP e non è disponibile a `collaboratore`. Riscrivere il valore di un lavoro
già fatto è più vicino alla configurazione che alla scrittura di un'entità — la stessa lettura dello
slice 1 §6.3 che lo slice 3 §11 ha applicato all'emissione.

---

## 6. Denaro, ore e arrotondamenti

Nessun `float`, in nessun punto: `Decimal` nel servizio, `Numeric` in Postgres, totali **calcolati
dal servizio e restituiti già fatti**. È la regola dello slice 3 §6, e qui ha una conseguenza in più:
**il frontend di questo slice non calcola nessun totale economico.** Ogni cifra del P&L e del
preventivo-vs-consuntivo arriva dall'API già sommata. L'unica somma ammessa nel browser è quella
delle ore visibili in una settimana, e si fa in centesimi interi con il precedente che esiste già,
`centsFromDecimalString` (`apps/web/src/features/deals/columns.tsx:130`), generalizzato in
`lib/decimal.ts` come `scaledFromDecimalString(value, scale)` — tre feature ne hanno bisogno adesso.

### 6.1 Tre tipi, non due

| Grandezza | Tipo | Perché |
|---|---|---|
| `costs.importo`, ogni riga e ogni totale del P&L | `Numeric(12,2)` | Sono importi che compaiono a schermo e su un documento: la convenzione dello slice 1 |
| `time_entries.ore`, `deals.ore_preventivate` | `Numeric(8,2)` | Ore, non denaro: la convenzione dello slice 1 |
| `tariffa_oraria`, `tariffa_applicata`, `costo_orario_default`, `costo_applicato` | **`Numeric(12,6)`** | Sono **fattori**, non importi |

Il terzo tipo non è un vezzo: è **imposto dallo slice 3**. `invoice_lines.prezzo_unitario` è
`Numeric(12,6)` (slice 3 §6, con la sua motivazione: *«3 ore a 33,3333 €/h non è esprimibile a due
decimali»*). Se la tariffa oraria qui fosse a due decimali, convertire delle ore in una riga di
fattura cambierebbe il numero al passaggio, e la riconciliazione del §14 criterio 5 fallirebbe di
qualche centesimo per motivi che nessuno saprebbe ricostruire. La tariffa e il prezzo unitario sono
**la stessa grandezza vista da due tabelle**, quindi hanno la stessa precisione.

Gli schemi Pydantic riportano `max_digits`/`decimal_places` di ogni colonna, come già fa
`deals/schemas.py` con la sua motivazione documentata: senza, un valore fuori capacità arriva a
`flush()` e torna come `NumericValueOutOfRange` grezzo, che non è un `IntegrityError` e non ha
handler; e con `expire_on_commit=False` la risposta immediata riporterebbe il valore non arrotondato,
cioè mentirebbe su ciò che è stato scritto.

### 6.2 Le due regole, e a quale livello si somma

1. **Riga:** `valore_riga = ROUND(ore × tariffa_applicata, 2)`, `ROUND_HALF_UP`. Half-up e non
   half-even, ereditato dallo slice 3 §6.1: è la prassi fiscale italiana, ed è ciò che l'aritmetica
   dei controlli SdI si aspetta sulla riga di fattura che nascerà da queste ore.
2. **Aggregato = somma dei `valore_riga` già arrotondati**, mai arrotondamento della somma esatta.

Le due danno risultati diversi, di qualche centesimo, e va deciso qui invece di scoprirlo davanti a
un cliente. Vince la prima per una ragione specifica di questo slice: **il valore di riga è ciò che
il rapporto ore stampa accanto a ogni voce**, e un totale che non è la somma della colonna visibile è
il modo più rapido per far perdere fiducia a un cliente in un documento che gli stai mandando per
farti pagare. Quando le due divergono, **vincono le righe stampate**.

C'è un caso in cui questa regola **non** si applica, ed è importante che sia esplicito: quando le ore
diventano una riga di fattura raggruppata (§9.2), la riga porta `quantita = Σ ore` e
`prezzo_unitario = tariffa`, e il suo `prezzo_totale` è `ROUND(Σore × tariffa, 2)` — che può
differire di qualche centesimo da `Σ ROUND(ore × tariffa, 2)`. **Non è una discrepanza da
riconciliare**, perché il valore derivato smette di essere consultato nel momento in cui la fattura
esiste (§3, decisione 2). Il §7.1 lo dice come regola e il §14 criterio 5 lo verifica.

### 6.3 La data di una voce

`time_entries.data` e `costs.data` sono `Date`, non `timestamptz`. Non sono istanti: sono il giorno di
calendario a cui il lavoro o la spesa appartengono, ed è quel giorno che determina in quale mese
finiscono e quindi in quale rapporto e in quale periodo. `toISOString()` su un istante sposta di un
giorno tutto ciò che accade dopo le 23:00 CET, e il 31 del mese sposta di un mese: è esattamente il
difetto di the previous system al §2.2, ed è la stessa conclusione dello slice 3 §6.2 su `data_emissione`.

Ammessa la retrodatazione, e **senza il limite d'anno** che lo slice 3 §6.2 impone alla data di
emissione. La differenza è nell'oggetto, non nella disciplina: là si scrive in un registro fiscale
progressivo, dove inserire in un anno chiuso è sbagliato indipendentemente da tutto; qui si dichiara
quando è stato fatto un lavoro, e un consulente registra il venerdì il lunedì, e a fine gennaio
chiude dicembre. Vietare la retrodatazione produrrebbe ore datate al giorno in cui ci si è ricordati
di scriverle, cioè un archivio che mente sul suo unico dato temporale.

Rifiutata invece la data **futura**: un'ora non ancora lavorata non è un dato, è una previsione, e
questo slice non fa previsioni (§13).

### 6.4 Chiusura di periodo — l'altra metà della garanzia

Il §5 impedisce che **cambiare una tariffa** riscriva un margine già letto. Resta un secondo modo di
cambiarlo, e va chiuso o la garanzia è metà: **registrare oggi un'ora datata a marzo scorso.** Non è
un abuso, è la retrodatazione appena ammessa, ed è legittima finché il periodo è aperto.

```
period_locks(anno INTEGER, mese INTEGER, chiuso_il timestamptz, chiuso_da UUID FK users,
             PRIMARY KEY (anno, mese))
```

Un `admin` chiude un mese quando ne ha riportato i numeri. Da quel momento ogni scrittura — creazione,
modifica di `data` o `ore`, cancellazione — su una `time_entry` o un `cost` **datati dentro un mese
chiuso** viene rifiutata con `Conflict`, che nomina il mese e chi l'ha chiuso. La riapertura esiste,
è `admin`, e scrive un'activity: un periodo non si riapre per sbaglio e non si riapre in silenzio.

Due proprietà deliberate. **Chiudere non è obbligatorio**: chi non chiude niente ha il comportamento
di prima, e nessuna schermata pretende un rito prima di funzionare. E **la chiusura non congela le
fatture**, che hanno già le loro regole nello slice 3 §4 e non ne vogliono una seconda: `period_locks`
governa soltanto le due tabelle di questo slice.

Il P&L di periodo riporta accanto al totale se il periodo è chiuso e, quando è aperto, **quante voci
sono state scritte dopo la fine del periodo a cui appartengono** (`created_at > fine_periodo`). È
l'informazione che dice a chi legge se quel numero può ancora muoversi, ed è gratuita: è un `COUNT`
su due colonne che ci sono già.

---

## 7. Il conto economico

### 7.1 Le righe, e da dove viene ciascuna

Per un singolo deal:

| Riga | Sorgente esatta |
|---|---|
| **Ricavi** | `Σ invoices.imponibile` su `invoices` con `deal_id = :deal`, `tipo = 'fattura'`, `stato = 'emessa'`, `deleted_at IS NULL` |
| **Costi diretti** | `Σ costs.importo` con `deal_id = :deal`, `deleted_at IS NULL` |
| **Costo del lavoro** | `Σ ROUND(ore × costo_applicato, 2)` sulle `time_entries` del deal, non cancellate, con `costo_applicato IS NOT NULL` — **comprese le non fatturabili**: una riunione interna costa esattamente quanto costerebbe se la si fatturasse, ed escluderla farebbe sembrare più redditizio il deal che ne ha richieste di più |
| **Margine lordo** | Ricavi − Costi diretti − Costo del lavoro |
| **Margine %** | `margine / ricavi × 100`, arrotondato a 2 decimali. **`null` se ricavi = 0** |
| *(informative)* | Ore totali, ore fatturabili non fatturate, valore maturato, ore senza tariffa |

Cinque decisioni dentro quella tabella, ognuna con la sua ragione.

**`imponibile`, non `totale`.** Il `totale` comprende l'IVA, che non è ricavo: è denaro riscosso per
conto dello Stato. Sotto forfettario le due cifre coincidono perché l'imposta è zero, quindi oggi la
differenza non è osservabile — ed è esattamente per questo che va scritta oggi, con lo stesso
argomento con cui lo slice 3 §6.1 fissa le regole di arrotondamento che il forfettario non esercita.
Il §14 criterio 1 la verifica con un profilo `RF01` sintetico.

**Emessa, non annullata, non proforma, non bozza.** Una proforma non è un ricavo per definizione
(slice 3 §5: non tocca il registro). Una fattura annullata conserva il numero ma non il ricavo: è la
pagina barrata del registro cartaceo.

**Ricavo = fatturato, non incassato.** Tre ragioni: è l'unica cifra che si riconcilia con un documento
che esiste e ha un numero; l'incasso è già modellato dallo slice 3 come `stato_pagamento` e
`data_incasso`, quindi confonderli farebbe muovere il margine di un lavoro finito il giorno in cui il
cliente si decide a pagare; e un conto economico per cassa è **un altro report**, che questo slice
nomina, per il quale indica il filtro che lo produrrebbe (`data_incasso` invece di `data_emissione`),
e che non consegna (§13).

**Il bollo non è un costo di deal.** Lo slice 3 §7.2 lo tiene fuori dal totale e a carico
dell'emittente. Farlo comparire come costo del deal richiederebbe che questo slice guardasse dentro
la composizione fiscale di una fattura, che è competenza dello slice 3. Se l'utente lo vuole nel
margine, lo registra come un normale `cost`.

**Margine % è `null`, non `0`, quando i ricavi sono zero.** Zero per cento vuol dire «tutto quello
che ho incassato se n'è andato in costi»; qui non si è ancora incassato niente. Sono due fatti
diversi e il report non li appiattisce (§14 criterio 6).

### 7.2 Il costo del lavoro non è un costo due volte

`costs` e il costo del lavoro sono **insiemi disgiunti per costruzione**: `costs` contiene denaro
uscito verso terzi, il costo del lavoro deriva da `time_entries`. Un consulente esterno che ti
fattura le sue ore è un `cost` di categoria «Consulenza esterna» e le sue ore, se le registri, vanno
con `costo_applicato = NULL` — oppure non le registri affatto. Il §14 criterio 4 verifica che non
esista nessun percorso in cui la stessa spesa entra da entrambe le parti.

### 7.3 Cosa mostra un deal incompleto

Un deal con 20 ore registrate e nessuna fattura ha ricavi `0.00`, costi positivi e margine negativo.
Non è una perdita: è un lavoro non finito. Il report non mostra mai quel numero nudo, mostra uno
**stato**, derivato dai dati e non da una colonna:

| Stato | Condizione | Cosa significa il margine |
|---|---|---|
| `in corso` | stage `tipo = 'open'` | **provvisorio**. Accanto compare il *valore maturato* = ricavi fatturati + `Σ ROUND(ore × tariffa_applicata, 2)` sulle ore fatturabili non fatturate. Non si chiama mai «margine» |
| `da fatturare` | stage `won`, esistono ore `fatturabile = true` e `invoice_line_id IS NULL` | provvisorio, con il valore ancora da emettere in evidenza |
| `chiuso` | stage `won` o `lost`, nessuna ora fatturabile non fatturata | **definitivo**. È l'unico stato in cui la cifra è riportabile |

Il valore maturato **non è ricavo** e non entra in nessuna riga del P&L: è la stima del §3 decisione
2, e vive in una colonna con un'altra intestazione.

### 7.4 Il P&L di periodo, e le spese generali

Aggregato su un intervallo di date, con filtro facoltativo per cliente. Ogni grandezza è attribuita
al periodo dalla **sua** data: i ricavi da `invoices.data_emissione`, i costi da `costs.data`, il
costo del lavoro da `time_entries.data`. Non dalla data del deal, che non esiste, e non da un'unica
data comune, che nessuna delle tre ha.

Il totale è presentato **in due colonne**: *deal chiusi* e *deal in corso*. Il numero riportabile è
il primo. Sommare il margine di un lavoro finito con quello di uno a metà produce una cifra che non è
né l'uno né l'altro, e che cambia ogni settimana per ragioni che non sono andamento aziendale.

Un costo con `deal_id IS NULL` è una **spesa generale**: entra nel P&L di periodo, in una riga sua, e
**non viene ripartito su nessun deal**. Qualunque chiave di ripartizione — sul ricavo, sulle ore — è
arbitraria, e ha una conseguenza precisa e inaccettabile: **il margine di un deal si muoverebbe
quando viene fatturato un deal diverso**. È proprio la proprietà che rende un numero non riportabile,
ed è il difetto che il P&L di the previous system ha per la fiscalità (§8).

---

## 8. Il calcolo fiscale, spostato dove ha senso

the previous system calcola, dentro `App.jsx` e per singola offerta:

```js
const taxableBase   = gross * FORFETTARIO_PROFITABILITY_RATE   // 0.67
const substituteTax = taxableBase * FORFETTARIO_SUBSTITUTE_TAX_RATE  // 0.05
const inps          = (taxableBase - substituteTax) * FORFETTARIO_INPS_RATE  // 0.2607
const net           = gross - substituteTax - inps
```

È sbagliato in tre modi indipendenti, e nessuno dei tre si cura correggendo la formula:

1. **L'INPS non è proporzionale al ricavo di un progetto.** Ha un minimale — si paga anche a reddito
   zero — e un massimale. Ripartirla pro-rata su un singolo lavoro attribuisce a quel lavoro una
   quota che non dipende da lui.
2. **Il coefficiente di redditività si applica al totale dell'anno**, non a un progetto. Applicarlo a
   una fetta e sommare le fette dà un altro numero.
3. **Il risultato cambia retroattivamente.** Il «profitto» di un progetto di marzo dipende da quanto
   si fattura a novembre, perché entrambi concorrono alla stessa base. È la proprietà che il §7.4
   rifiuta per le spese generali, qui applicata all'intera fiscalità.

**Questo slice consegna un margine lordo ante imposte**, e sposta il calcolo fiscale dove è corretto:
un report **di periodo**, mai per deal, in `packages/core`, che legge `fiscal_profile` e produce
imponibile, imposta sostitutiva, contributi e reddito netto stimato per un anno. È la migrazione delle
tre costanti da `App.jsx` al service layer che lo slice 1 §14 assegna a questo slice — con la
correzione che il livello giusto non è quello che the previous system aveva scelto.

Il report è dichiaratamente una **stima** e lo scrive in testa: minimale, massimale, altri redditi e
acconti restano fuori (§13). Una stima etichettata è utile; una stima presentata come un consuntivo è
il difetto originale in una forma nuova.

---

## 9. Preventivo vs consuntivo

È la riga che la decomposizione indica come titolo dello slice, ed è quella che dice a un consulente
se il lavoro valeva il prezzo.

### 9.1 Le grandezze

| | Preventivo | Consuntivo |
|---|---|---|
| Ore | `deals.ore_preventivate` | `Σ time_entries.ore` |
| Valore | `deals.valore_preventivato` | Ricavi fatturati (§7.1) |
| Tariffa media | `valore_preventivato / ore_preventivate` | `ricavi / ore` |

La terza riga non è nella decomposizione ed è quella che serve di più: **quanto ho realizzato per ora
di lavoro, contro quanto pensavo di realizzare.** Sono due numeri confrontabili anche fra deal di
dimensioni diverse, e sono la sola forma in cui la domanda «questo cliente conviene?» ha una risposta
numerica.

### 9.2 Cosa rende onesto il confronto quando il lavoro è a metà

**Il confronto del valore è contro il preventivo pro-rata, non contro il preventivo pieno.** La riga
porta `avanzamento_ore = ore_consuntivate / ore_preventivate`, e lo scostamento di valore si calcola
contro `valore_preventivato × avanzamento_ore`, con il preventivo pieno mostrato **accanto**, non al
suo posto. Al 40% delle ore, essere al 40% del valore preventivato è in linea; confrontare con il
100% marcherebbe ogni lavoro in corso come sotto-performante, e un report che segnala tutto non
segnala niente.

Il pro-rata richiede **entrambe** le colonne di preventivo. Con `valore_preventivato` valorizzato e
`ore_preventivate` nullo non esiste un avanzamento da cui derivarlo: la riga mostra allora il solo
confronto assoluto, marcato `pro_rata_non_calcolabile`, invece di inventare un avanzamento dal valore
fatturato — che sarebbe circolare, perché il valore fatturato è proprio la grandezza da giudicare.

**Un preventivo assente non è un preventivo di zero.** `ore_preventivate IS NULL` significa che
nessuno ha stimato. La riga mostra «non preventivato», è **esclusa** dagli aggregati di budget, e non
viene contata come scostamento del 100%. Nessuna divisione per un preventivo pari a zero o nullo
viene mai eseguita: il servizio restituisce `null` per gli scostamenti percentuali di quelle righe.

**Qui il residuo A14 smette di essere un fastidio e diventa un difetto di correttezza.** Oggi
`DealUpdate` non ha nessuna grafia per riportare `ore_preventivate` a `NULL`: `""` dà 422, `null`
viene scartato da `exclude_none=True`, la chiave omessa non fa niente, e l'unica cosa che scrive è
`"0.00"`. Quindi l'unico modo raggiungibile per dire «non c'è preventivo» dopo averne inserito uno
sbagliato è `0.00`, che **questo report leggerebbe come "preventivate zero ore, sforamento
infinito"**. `NULL` e `0` significano cose opposte in questa tabella, e una delle due non è
scrivibile.

Questo slice deve quindi **chiudere A14**, adottando `exclude_unset=True` con `model_fields_set` al
posto di `exclude_none=True`. Il residuo stesso dice che è un cambio di contratto su tutti i servizi
e che merita un task suo: qui quel task diventa un prerequisito, non un'opzione. La difesa
secondaria resta comunque: `ore_preventivate = 0` è trattato come «non confrontabile», mai come
denominatore.

---

## 10. Dalle ore alla fattura, e ai documenti

### 10.1 Il ponte con lo slice 3, senza duplicarlo

`POST /api/deals/{id}/time-entries/to-invoice-draft` **non emette niente e non calcola nessun
totale**: costruisce un `InvoiceCreate` con le sue righe e chiama `InvoiceService`, che resta l'unico
proprietario di numerazione, validazioni fiscali, arrotondamenti e congelamento (slice 3 §3, §6, §9).

**Raggruppamento delle righe: una riga per `(tariffa_applicata, mese)`**, con
`quantita = Σ ore`, `prezzo_unitario = tariffa_applicata`, e descrizione
«Attività *mese* — *N* ore». Non una riga per voce: una fattura con quaranta righe è illeggibile per
il cliente e il dettaglio ha già il suo posto, che è il rapporto ore allegato (§10.2). Il
raggruppamento è modificabile nel dialogo prima di generare la bozza.

Cosa **non** entra mai in una bozza: le voci con `fatturabile = false`, per definizione; le voci con
`tariffa_applicata IS NULL`, perché una riga di fattura senza prezzo unitario non è emettibile e
inventarne uno qui significherebbe decidere al posto dell'utente quanto vale il suo lavoro — il
servizio le rifiuta con `ValidationFailed` che **le conta e le elenca**, così la risposta è
un'istruzione («dai una tariffa a queste sei voci») e non un ostacolo; e le voci già legate a una
riga di una fattura emessa.

**Il legame si scrive quando nasce la riga di bozza**, non all'emissione:
`time_entries.invoice_line_id` punta alla riga, la FK è `ON DELETE SET NULL`, e l'immutabilità
scatta sullo **stato della fattura** (§4.3). Questo evita di dover toccare la transazione bloccata
dello slice 3 §3, che è la parte del sistema che meno di ogni altra vuole nuovi partecipanti: finché
la fattura è bozza le ore restano modificabili e la sostituzione in blocco delle righe (slice 3 §11)
le scollega e ricollega senza lasciare orfani; nel momento in cui `issue()` fa il commit, le ore
legate sono congelate senza che `issue()` abbia dovuto sapere della loro esistenza.

Un'ora già legata a una riga di una fattura emessa **non è più selezionabile** per una nuova bozza, e
il servizio lo rifiuta con `Conflict` nominando la fattura. È il meccanismo che impedisce di
fatturare due volte lo stesso lavoro, ed è al livello del servizio perché è dove sta l'informazione.

### 10.2 Il rapporto ore

Un `template` dello slice 2, di `tipo = 'rapporto_ore'`, reso dalla pipeline `{{}}` → Pandoc → Typst
già esistente, archiviato come `document` di tipo `rapporto_ore` sul deal. `documents.tipo` è
`String(20)` più un `Literal` Pydantic, non un `ENUM` Postgres — il modello lo dice esplicitamente e
per questa ragione — quindi il valore nuovo costa una costante, non una migrazione.

Il layout è quello di `template-time-tracking.typ` (§2.1). Cosa cambia: `[COMPANY_NAME]` e i suoi
fratelli diventano `{{emittente.*}}` da `emitter_profile`; `[ENTRIES_PLACEHOLDER]`, oggi riempito
concatenando sorgente Typst in JavaScript, diventa `{{#each voci}}`; e l'escaping è quello per
contesto dello slice 2, applicato **una volta sola** al valore di dominio.

L'XLSX è prodotto da `openpyxl` nell'immagine dell'API. Si porta la forma del foglio (§2.1); si
riscrivono tre cose:

- ore e importi scritti come **numeri** con `number_format`, non come stringhe già formattate;
- la data scritta come **data**, non come stringa;
- il totale scritto come formula **`SUBTOTAL(109; ...)`**, non come costante. Chi riceve un timesheet
  lo filtra, e un totale costante dopo un filtro è un numero che contraddice la colonna sopra —
  esattamente lo stesso principio del §6.2.

### 10.3 Il giustificativo di un costo

`costs.document_id` punta a un `document` dello slice 2, con il suo storage pluggable, il suo
versioning e il suo hash. the previous system teneva l'allegato come base64 dentro il JSON dei costi
(`parseBase64Payload`, `vite.config.js:1017`): il documentale esiste già e non si reinventa, che è la
stessa conclusione dello slice 3 §8.4.

---

## 11. Superficie MCP e API

La regola non negoziabile resta: **i tool MCP e i router FastAPI chiamano gli stessi servizi
in-process**, e il test di architettura lo verifica.

**Un agente può registrare e leggere. Non può cambiare quanto vale ciò che è già registrato.**

| Operazione | API | MCP |
|---|---|---|
| `log_time` — registra una voce di ore | sì, `collaboratore` | **sì** |
| `update_time_entry`, `delete_time_entry` (solo non fatturate) | sì, `collaboratore` | sì |
| `list_time_entries`, `get_deal_time_summary` | sì | sì |
| `create_cost`, `update_cost`, `delete_cost` | sì, `collaboratore` | sì |
| `list_cost_categories` | sì | sì |
| `get_deal_pnl`, `get_period_pnl`, `get_budget_vs_actual` | sì | sì |
| `describe_rates` (quali tariffe si applicherebbero a una nuova voce) | sì | sì |
| `recalculate_rates` | sì, `admin` | **no** |
| `update_user_rates`, `update_deal_rate` | sì, `admin` | **no** |
| `create/update/archive_cost_category` | sì, `admin` | **no** |
| `bind_time_to_invoice` (`to-invoice-draft`) | sì, `admin` | **no** |
| `close_period`, `reopen_period` | sì, `admin` | **no** |
| `get_fiscal_estimate` | sì, `admin` | **no** |

Cinque ragioni, nessuna delle quali è diffidenza generica verso gli agenti.

1. **Registrare le ore è l'operazione agentica più preziosa del prodotto, e la più sicura.** «Claude,
   ho fatto tre ore ieri sul progetto Rossi» è il caso d'uso che fa risparmiare tempo ogni settimana,
   che è il criterio dichiarato dallo slice 1 §1. Ed è l'opposto di `issue_invoice`: una voce è
   reversibile (soft delete), attribuita (`actor_type = 'mcp'` sull'activity), e limitata a un deal e
   a un giorno. Vietarla per simmetria con lo slice 3 significherebbe non aver capito perché lo slice
   3 vietava.
2. **Ciò che un agente non può fare è cambiare il significato di numeri già registrati.**
   `recalculate_rates`, le colonne di tariffa e la tassonomia dei costi alterano tutte il senso di
   righe **passate**. È precisamente il fallimento che il §5 esiste per impedire, e sarebbe assurdo
   chiuderlo nel modello dati e lasciarlo aperto attraverso un tool.
3. **`bind_time_to_invoice` è l'operazione che diventa irreversibile.** Legare le ore a una bozza è
   innocuo finché la bozza è tale, ma è il passo che ne determina il congelamento all'emissione, e la
   scelta di *quali* ore fatturare è una decisione commerciale. Lo slice 3 §11 ha già ritirato
   `issue_invoice` con lo stesso ragionamento; questo è il gradino immediatamente precedente.
4. **`get_fiscal_estimate` è l'unica esclusione di una sola lettura, e la ragione è diversa dalle
   altre.** Non riguarda la reversibilità: riguarda il fatto che il reddito imponibile, i contributi
   e il netto stimato di una persona reale sono il dato più sensibile che questo prodotto contenga, e
   che un PAT senza scope (R10) è oggi indistinguibile da un accesso completo. Finché «dai un token a
   Claude» significa «dai il tuo account» — parole del residuo R10 — la stima fiscale non entra in un
   contesto conversazionale per una richiesta generica sui deal. `close_period` e `reopen_period`
   ricadono invece sotto la ragione 2: chiudere un mese cambia cosa si può ancora scrivere nel
   passato, riaprirlo lo rimette in gioco.
5. **La difesa è strutturale perché quella per permessi non esiste.** Il residuo R10 è aperto: un PAT
   non ha scope ed eredita il ruolo pieno del proprietario, quindi «l'MCP non ricalcola le tariffe»
   non è imponibile con un controllo di autorizzazione — un token amministrativo lo passerebbe. Si
   impone **non registrando il tool**, che è l'unico meccanismo che tiene finché R10 è aperto.

**Il divieto va reso meccanico.** Il test di architettura dello slice 3 §11 cresce: per ogni metodo
pubblico di `TimeEntryService`, `CostService` e `AnalyticsService`, o esiste un tool MCP che lo
chiama, o il metodo è in una lista di esclusione dichiarata — e la lista deve essere **esattamente**
questi dieci nomi: `recalculate_rates`, `update_user_rates`, `update_deal_rate`,
`create_cost_category`, `update_cost_category`, `archive_cost_category`, `bind_time_to_invoice`,
`close_period`, `reopen_period`, `get_fiscal_estimate`.

**`log_time` accetta un `deal_id`, mai un nome di deal, e non crea niente che non trovi.** Un agente
che risolve «il progetto Rossi» sul deal sbagliato attribuisce ore fatturabili al cliente sbagliato,
e l'errore emerge soltanto su una fattura. Il tool `search_deals` esiste già dallo slice 1: la
risoluzione è un passo separato, visibile nella conversazione, e la sua ambiguità è un problema
dell'agente e non un dato scritto in silenzio.

Endpoint:

```
GET  POST   /api/time-entries                        lista con filtri (deal, utente, periodo, fatturabile, fatturato)
PATCH DELETE /api/time-entries/{id}
GET         /api/deals/{id}/time-entries
GET  POST   /api/costs                               ; PATCH DELETE /api/costs/{id}
CRUD        /api/cost-categories                     (admin)
GET         /api/deals/{id}/pnl
GET         /api/deals/{id}/budget
GET         /api/analytics/pnl?from=&to=&customer_id=
GET         /api/analytics/budget?from=&to=
GET         /api/analytics/fiscale?anno=             (admin)
GET  POST   /api/period-locks                        chiusura di periodo (admin) ; DELETE /api/period-locks/{anno}/{mese}
PUT         /api/users/{id}/rates                    (admin)
PUT         /api/deals/{id}/rate                     (admin)
POST        /api/deals/{id}/rates/recalculate        (admin)
POST        /api/deals/{id}/time-entries/to-invoice-draft   (admin)
GET         /api/deals/{id}/time-report?formato=pdf|xlsx&mese=AAAA-MM
```

Risorse MCP: `deal://{id}` (già esistente) acquisisce ore consuntivate, valore maturato e stato del
§7.3 nel suo Markdown — è il modo di far **leggere** prima di far **agire** che lo slice 1 §8.4
descrive, applicato all'unica cosa che un agente vuole sapere prima di registrare un'ora.

---

## 12. Residui degli slice precedenti che toccano questo

| Residuo | Interazione |
|---|---|
| **R1** — la sessione condivisa del server MCP non è sicura in concorrenza | **Bloccante per questo slice, a differenza dello slice 3.** Lo slice 3 poteva convivere con R1 perché l'MCP non emetteva e quindi non scriveva niente di critico; qui `log_time` è un tool di **scrittura** ed è il tool centrale della superficie agentica. La misura del reviewer sullo slice 1A — 10 scritture concorrenti, 0 successi e 0 righe — descrive esattamente ciò che accadrebbe. **La cura (una sessione per chiamata, `session_provider` + `contextvars`) è un prerequisito di `log_time`**, e il §14 criterio 11 la verifica |
| **R3** — un utente disattivato può essere `owner_id` di un deal | Diventa una domanda concreta, e questo slice le dà una risposta: `TimeEntryService` valida `user_id` con `UserRepository.get_active` in **creazione e modifica** — che esiste già e fa esattamente questo controllo — e legge con `get` semplice, così le ore storiche di chi non lavora più qui restano nel P&L, nei documenti e con il suo nome. Il denaro è stato speso davvero. **La stessa risposta si propone per `owner_id`**: un'assegnazione esistente sopravvive, una nuova si rifiuta |
| **A14** — `Update` non sa azzerare una colonna numerica o di data | **Va chiuso in questo slice**, §9.2: `NULL` e `0` su `ore_preventivate` significano cose opposte per il report e una delle due non è scrivibile |
| **A13** — una chiave custom può collidere con una colonna nativa | **Va chiuso in questo slice**, §4.6: le colonne native qui si chiamano `ore`, `data`, `importo`, `descrizione`, cioè le etichette che un utente digiterebbe per prime |
| **R5** — nessun audit trail per la configurazione | Chiuso per tariffe, categorie di costo e parametri fiscali (§4.5), come lo slice 3 l'ha chiuso per `fiscal_profile`. Aperto per il resto |
| **R10** — i PAT sono senza scope | È la ragione 4 del §11: la difesa è strutturale perché quella per permessi non esiste |
| **R13** — la promessa che `entity_type` sia «aperto» è inesatta | §4.6, scritto nella forma corretta invece che ripetuto nella forma smentita |
| **R7** — nessun indice parziale su `deleted_at` | Le due nuove tabelle nascono con gli indici parziali giusti (§4.1). Il difetto generale resta |
| **R9** — l'ordinamento promesso non esiste | Un elenco di ore senza ordinamento per data è inutilizzabile: `time_entries` e `costs` nascono con l'ordinamento, ma il residuo generale sulle altre entità resta aperto |
| **B3** — la board Kanban carica anche i deal chiusi, per sempre | Peggiora qui: la vista margini è per sua natura una lista di deal **chiusi**, quindi la crescita illimitata smette di essere invisibile. Va paginata dall'inizio, con i filtri di periodo obbligatori |

---

## 13. Ciò che questo slice **non** fa

| Fuori ambito | Perché |
|---|---|
| **Timer / cronometro** | Argomentato, non rinviato: un cronometro richiede l'entità «sessione in corso», una storia di recupero per il browser chiuso e una per il secondo dispositivo. E il modo in cui il time tracking di un freelance fallisce davvero non è «ho dimenticato di fermare il timer», è **«non ho mai inserito martedì»**. La griglia settimanale (§15) e `log_time` via MCP attaccano quel fallimento; un cronometro no, e costa tre meccanismi |
| **Payroll, buste paga, presenze, ferie** | È un altro prodotto, con obblighi normativi propri. Le ore qui servono al margine, non alla retribuzione |
| **Redditività per persona** | I dati per calcolarla ci sono, e proprio per questo va detto che non si consegna: una classifica dei collaboratori per margine generato è una scelta gestionale, non una funzionalità, e non si abilita per inerzia perché lo schema lo permette |
| **Flusso di approvazione delle ore** | Presuppone un ruolo «approvatore» che i tre ruoli dello slice 1 §6.3 non hanno, e un secondo stato su ogni voce. In uno studio da poche persone aggiunge attrito senza aggiungere verità |
| **Multivaluta** | Slice 3 §13 fissa `Divisa = EUR`. Un secondo insieme di importi e uno storico dei cambi è un progetto suo, e sarebbe incoerente introdurlo dal lato costi mentre le fatture restano in euro |
| **Previsioni, forecast, capacity planning** | Un'ora futura non è un dato. Il preventivo (`ore_preventivate`) è già il solo impegno futuro che questo modello rappresenta, ed è inserito a mano da chi lo firma |
| **Conto economico per cassa** | Nominato al §7.1 con il campo che lo produrrebbe (`invoices.data_incasso`). Consegnarne due significa dover spiegare a ogni schermata quale dei due si sta guardando |
| **Ripartizione delle spese generali sui deal** | §7.4: ogni chiave di ripartizione fa muovere il margine di un deal quando ne viene fatturato un altro |
| **Riconciliazione bancaria e import automatico dei costi** | Leggere un conto è un'integrazione, non un conto economico. `costs` si inserisce a mano o si importa da CSV, e nemmeno il CSV è in questo slice |
| **Fatturazione a milestone, a canone o a scalare** | Sono modelli di ricavo con una loro macchina a stati. Qui le ore diventano righe di fattura, e basta |
| **Detraibilità IVA sugli acquisti** | §4.4: `importo` è il totale pagato, corretto in forfettario. Il punto di estensione è una colonna, nominato lì |
| **Minimale, massimale, acconti e altri redditi nel calcolo fiscale** | §8: il report è una stima etichettata come tale. Farne un consuntivo richiede il quadro completo dei redditi della persona, che questo prodotto non ha e non deve avere |

---

## 14. Criteri di successo

Eseguibili in CI, non da guardare.

1. **Un ricavo di P&L si riconcilia esattamente con le fatture che lo compongono.** Per un deal con
   tre fatture emesse, una annullata e una proforma, `GET /api/deals/{id}/pnl` restituisce un
   `ricavi` uguale **al centesimo** a `SELECT SUM(imponibile) FROM invoices WHERE deal_id = :id AND
   tipo = 'fattura' AND stato = 'emessa' AND deleted_at IS NULL`, eseguita come SQL diretto in un
   percorso indipendente dal servizio. Confronto su `Decimal`, mai su float. Ripetuto con un profilo
   `RF01` sintetico (quello che lo slice 3 §14.8 introduce nelle fixture) in cui `imponibile` e
   `totale` differiscono: il P&L deve seguire `imponibile`, e il test fallisce se segue `totale`.
2. **Ricalcolare un periodo passato non cambia un numero già riportato.** Si registrano 40 ore a
   80,000000 €/h su un deal, si legge `GET /api/analytics/pnl` per quel periodo e si conserva la
   risposta. Si porta `users.tariffa_oraria_default` a 120 e `deals.tariffa_oraria` a 150. Si rilegge
   lo stesso periodo: **il JSON è identico**, confrontato come struttura, non a occhio. Poi si
   registra una nuova ora e solo quella porta `tariffa_applicata = 150.000000`.
   Seconda metà, sull'altro modo di muovere lo stesso numero (§6.4): a periodo **chiuso**, un
   `log_time` datato dentro quel mese solleva `Conflict` nominando il mese e chi l'ha chiuso, e il
   P&L di quel periodo resta identico; a periodo **aperto**, la stessa scrittura riesce, il P&L
   cambia — e la risposta lo dichiara, riportando `periodo_chiuso = false` e
   `voci_scritte_in_ritardo = 1`.
3. **La sola via che tocca il passato è esplicita e non arriva alle ore fatturate.**
   `recalculate_rates` su un intervallo aggiorna le voci non fatturate e scrive un'activity per voce
   con vecchio e nuovo valore; sullo stesso intervallo contenente una voce legata a una fattura
   **emessa** solleva `Conflict` nominando quante voci e quale fattura, **senza aver modificato
   nessuna delle altre** — verificato rileggendole dopo il rifiuto. E la chiamata con ruolo
   `collaboratore` solleva `PermissionDenied`.
4. **Le somme sono `Decimal`, e nessun totale economico nasce nel browser.** Mille voci da 0,10 ore a
   33,333333 €/h: il totale del servizio coincide con `Σ ROUND(ore × tariffa, 2)` calcolato in un
   test indipendente, e il test calcola **anche** la somma in float per dimostrare che diverge. Un
   secondo test verifica sull'AST di `apps/web/src` che nessun modulo applichi `Number()`,
   `parseFloat` o `+` a un campo economico proveniente dall'API. E un terzo verifica che nessun
   percorso faccia entrare la stessa spesa sia come `cost` sia come costo del lavoro (§7.2).
5. **Righe di fattura e ore combaciano, e il valore derivato smette di contare.** Generando una bozza
   da 37 voci su tre tariffe e due mesi: nascono sei righe, `Σ invoice_lines.quantita` è
   **esattamente** `Σ time_entries.ore` delle voci legate, ogni voce è legata a una riga sola, e
   nessuna voce già legata a una fattura emessa è selezionabile. All'emissione, ogni voce legata
   solleva `ImmutableField` su `ore`, `data`, `tariffa_applicata` e `descrizione`, e
   `UPDATE time_entries SET deleted_at = now()` in **SQL diretto** viene rifiutato dal `CHECK`.
   Infine: il test asserisce che `pnl.ricavi` è il valore della fattura e **non** la somma dei valori
   derivati, esibendo un caso costruito in cui i due differiscono di centesimi.
6. **Un deal incompleto non mente.** Deal `open` con 20 ore e nessuna fattura: `ricavi = "0.00"`,
   `margine_percentuale = null` (non `"0.00"`), `stato = "in corso"`, `valore_maturato` valorizzato e
   in un campo con nome diverso da `ricavi`; e nel P&L di periodo compare nella colonna «in corso»,
   non in quella riportabile.
7. **Il preventivo pro-rata.** Deal da 100 ore e 10.000 €, 40 ore registrate, 4.000 € fatturati:
   `avanzamento = "40.00"`, `budget_pro_rata = "4000.00"`, `scostamento_valore = "0.00"`. Con 4.500 €
   fatturati lo scostamento è `"500.00"`, **non** `"-5500.00"`. Con `ore_preventivate = NULL` la riga
   riporta `non_preventivato = true`, tutti gli scostamenti a `null`, ed è assente dagli aggregati.
   Con `ore_preventivate = 0` il risultato è identico a `NULL` e nessuna divisione viene eseguita.
8. **Un utente disattivato.** Le sue 12 ore restano nel P&L, negli aggregati e nel PDF con il suo
   nome; `log_time` per lui viene rifiutato con `ValidationFailed` che nomina `user_id`, e la
   modifica di una sua voce esistente per riassegnarla a lui pure.
9. **Il divieto MCP è nel build.** Nessun tool MCP raggiunge i dieci metodi della lista di
   esclusione del §11, e la lista dichiarata è **esattamente** quei dieci nomi: aggiungere un tool
   per uno di essi rompe la build, togliere un nome senza aggiungere il tool la rompe pure. E
   `log_time` esiste ed è invocato in un test reale contro Postgres, distinguibile nella timeline per
   `actor_type = 'mcp'`.
10. **Il rapporto ore è un documento, non una stringa.** Una descrizione
    `Call con @mario su [fase 1] & #2 — "urgente"`, su due righe, compare **identica** nel PDF e
    nella cella XLSX, ri-letta dai due file e confrontata con la stringa in ingresso. L'XLSX ha le
    ore come celle numeriche con formato `0.00`, la data come cella data, e il totale come
    `SUBTOTAL(109;…)` — verificato leggendo la formula, non il valore. Il PDF viene dal template
    `{{}}` e da `emitter_profile`, e una `grep` sul sorgente dei template non trova il nome di nessun
    freelance.
11. **Scrittura concorrente via MCP.** Venti `log_time` simultanei su Postgres reale producono venti
    righe e venti activity, senza nessun errore di sessione. È R1 chiuso, ed è la condizione per cui
    il tool esiste.
12. **Il ciclo completo, dai due adapter.** Claude registra 8 ore su un deal via MCP e legge
    `deal://{id}` vedendo ore e stato; l'umano apre la tab Ore, genera la bozza di fattura, la emette
    dall'app; il P&L del deal passa il criterio 1; il rapporto ore del mese si allega alla fattura; la
    timeline del cliente mostra le due sequenze distinguendo `mcp` da `user`; e il tentativo di
    Claude di ricalcolare le tariffe non trova alcun tool da chiamare.

---

## 15. Interfaccia

- **Tab «Ore»** ed **«Economia»** su Deal, dentro `EntityDetailLayout`, che era già disegnato per
  riceverle (slice 1 §10.2). Tab «Economia» anche su Cliente, con la somma dei suoi deal.
- **`/ore`** — griglia settimanale: righe i deal su cui hai lavorato di recente, colonne i sette
  giorni, una cella si compila da tastiera. È la vista che attacca il fallimento vero del §13
  (martedì mai inserito), e mostra il totale della settimana per riga e per colonna, sommato in
  centesimi interi.
- **`/analisi/margini`** — la lista dei deal con ricavi, costi, margine, margine % e **stato**
  (§7.3), con filtro di periodo obbligatorio e paginazione dall'inizio (residuo B3).
- **`/analisi/preventivo-consuntivo`** — §9, con preventivo pieno e pro-rata affiancati.
- **`/analisi/fiscale`** — §8, con l'etichetta «stima» in testa alla pagina, non in fondo.
- **`/impostazioni/categorie-costo`**, **`/impostazioni/tariffe`** e **`/impostazioni/periodi`** (la
  chiusura del §6.4, con l'elenco dei mesi chiusi, da chi e quando).
- I campi custom di `time_entry` e `cost` passano da `DynamicFieldRenderer`, che copre già tutti i
  tipi: è il moltiplicatore che lo slice 1 §10.2 aveva previsto, e qui non costa niente.

---

## 16. Un solo piano o due

Giudizio onesto: è **una specifica, due piani**, e vanno eseguiti in quest'ordine.

**4A — Ore e costi.** `time_entries`, `cost_categories`, `costs`, `period_locks` con il suo controllo
in scrittura, la risoluzione e il congelamento delle tariffe, la griglia settimanale, il rapporto ore
PDF e XLSX, i tool MCP, la cura di R1 e la guardia di A13. Dipende da slice 1 e slice 2, **non da
slice 3**.

**4B — Analisi.** P&L per deal e per periodo, preventivo vs consuntivo, il ponte
`to-invoice-draft`, il report fiscale, la chiusura di A14, e la restituzione di `periodo_chiuso` /
`voci_scritte_in_ritardo` nei report. Dipende da 4A **e da slice 3 in `main`**.

`period_locks` sta in 4A e non in 4B benché serva a proteggere i report di 4B: il vincolo che deve
esistere è quello **in scrittura**, e va introdotto prima che ci siano mesi di ore scritte senza di
esso. Aggiungerlo dopo significherebbe decidere retroattivamente quali periodi erano chiusi.

Tre ragioni per separarli, non una preferenza estetica:

1. **Il criterio centrale di 4B non è eseguibile senza slice 3.** «Il ricavo si riconcilia con le
   fatture» presuppone che le fatture esistano. Tenere insieme i due piani significa che metà dei
   test di 4A resta bloccata dietro una dipendenza che non la riguarda.
2. **4A è utile da solo.** Un freelance che registra le ore e manda al cliente un timesheet
   professionale ha già il risparmio settimanale che lo slice 1 §1 pone come criterio di esistenza di
   ogni funzionalità. 4B aggiunge il giudizio economico, che è prezioso e non è urgente allo stesso
   modo.
3. **Le decisioni irreversibili stanno tutte in 4A.** Il congelamento della tariffa sulla riga e la
   precisione `Numeric(12,6)` non si cambiano dopo che ci sono dati. Metterle in produzione presto e
   farle usare vale più che consegnare il report una settimana prima.

4B **non comincia** finché slice 3 non è in `main`. Se lo slice 3 dovesse slittare, 4A si rilascia
comunque, e la tab «Economia» semplicemente non esiste ancora — cosa che l'utente capisce, a
differenza di una tab che mostra zeri.
