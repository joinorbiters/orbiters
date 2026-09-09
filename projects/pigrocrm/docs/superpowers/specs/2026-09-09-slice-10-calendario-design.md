# PigroCRM — Slice 10: Calendario

**Data:** 2026-09-09
**Stato:** approvato da Ivan il 2026-09-09 (richiesta: «una nuova funzionalità calendario, sotto
alla home nel menu laterale, con i giorni di lavoro loggati e le scadenze, e il modo di inserire
entrambi da qui»).

---

## 1. Perché questo slice esiste

Il CRM sa già tutto quello che serve, e in tre posti diversi. Le ore stanno in `/app/ore`, che
dal 2026-09-09 apre su un registro con la barra del timer e la griglia settimanale a un tab di
distanza. Le fatture da incassare stanno in `/app/fatture`. Gli impegni con una data non stanno da
nessuna parte, perché lo slice 7 è stato specificato e non costruito.

Manca la domanda che una persona si fa il lunedì mattina: **questo mese, cosa ho fatto e cosa
scade?** È una domanda per giorno, e nessuna delle tre pagine risponde per giorno: il registro
risponde per riga, la griglia per settimana, le fatture per stato.

Il calendario non aggiunge un modello: aggiunge la vista mensile di quello che esiste, più
l'entità che allo slice 7 mancava di essere costruita.

---

## 2. Cosa mostra, e da dove viene ogni cosa

Tre livelli, e la loro differenza è deliberata: due si leggono, uno si scrive.

| Nel calendario | Da dove | Si crea da qui? |
|---|---|---|
| Le ore del giorno, con il totale e il dettaglio per deal | `time_entries.data` | **Sì** — vedi §4 |
| Le attività con scadenza in quel giorno | `attivita.scadenza` (§3) | **Sì** — vedi §5 |
| Le fatture emesse e non incassate che scadono in quel giorno | `invoices.data_scadenza` con `stato_pagamento <> 'incassato'` | **No**, e non è una mancanza |

**Perché la scadenza di una fattura non si crea dal calendario.** È un dato *derivato* dalla
fattura: la si stabilisce emettendo (o importando) il documento, e cambiarla dal calendario
significherebbe modificare una fattura da una vista che non mostra né il numero, né l'imponibile,
né lo stato. Nel calendario è un promemoria che rimanda alla fattura, e il posto per cambiarla è la
fattura.

**Cosa resta fuori, per ora.** La `data_chiusura_prevista` dei deal aperti. È una stima
commerciale, si sposta di continuo, e in un calendario che serve a sapere cosa scade davvero
sarebbe la riga che insegna a ignorare le righe. Aggiungerla è un `if` in `CalendarService`, e la
decisione di non aggiungerla è questa frase.

---

## 3. `attivita`: l'entità dello slice 7, costruita adesso

Il modello è **quello dello spec del 2026-09-03** (`2026-09-03-slice-7-attivita-e-promemoria-design.md`
§3), senza modifiche: `titolo`, `note`, `scadenza` *nullable*, `stato` fra `aperta` / `completata` /
`annullata`, `completata_il`, `assegnata_a`, al massimo uno fra `customer_id` / `person_id` /
`deal_id` / `invoice_id`, `origine`, `regola`, `custom_fields`, `deleted_at`. I tre indici di §3.3.

Questo slice costruisce l'entità e la sua superficie (API, MCP, calendario). **Non** costruisce il
pannello «Oggi» di §5 dello slice 7 né le automazioni di §6: sono lo stesso modello viste da un
altro lato, e arrivano quando servono.

**La conseguenza di `scadenza` nullable, nel calendario.** Un'attività senza data non è di oggi e
non è in ritardo: non si può disegnare in una casella. Compare in una sezione «senza scadenza»
sotto la griglia, mai in un giorno. È la stessa regola che lo slice 7 scrive per il pannello Oggi e
che lo slice 6C ha già dovuto imparare su `documents.stato_dal`: **un `NULL` non è zero giorni.**

---

## 4. Loggare un giorno di lavoro

Riuso di `time_entries`, con il deal obbligatorio, che è la decisione dello slice 4: il lavoro non
attribuibile a un cliente resta fuori, altrimenti diventa gestione paghe. Il calendario non la
riapre.

Dal giorno si apre un pannello con due bottoni. «Giornata» compila **8 ore** e chiede solo il deal;
«Ore» lascia scrivere il numero. Entrambi passano da `POST /api/time-entries`, quindi la tariffa si
congela, la chiusura di periodo rifiuta e la riga di attività viene scritta esattamente come per
ogni altra ora: il calendario è un modo di compilare quel form, non una seconda strada per scrivere
sulla stessa tabella.

Le otto ore sono un default e non una regola: si cambiano nel campo prima di salvare, e non esiste
nessuna colonna «giornata» da nessuna parte. Una giornata è otto ore su un deal, e resta una riga di
ore come tutte le altre — la si modifica e la si cancella dal registro di `/app/ore`, che è dove
vive la modifica.

---

## 5. Inserire una scadenza

Dal giorno, «Nuova scadenza» crea un'`attivita` con `scadenza` a quel giorno, `origine = 'manuale'`
e, se il pannello è stato aperto da una scheda, il riferimento a quell'entità. Nel calendario si può
anche **completare** (`stato = 'completata'`, `completata_il = today_local()`) e **annullare**, che
sono i tre stati dello slice 7 e non due: sei mesi dopo la domanda non è «è sparita», è *perché*.

---

## 6. La lettura del mese

`GET /api/calendario?mese=YYYY-MM`, un solo giro. Tre query — ore per giorno, attività per
intervallo, fatture per intervallo — assemblate da `CalendarService`, in `packages/core`, perché è
la stessa lettura che serve alla web app e all'agente: metterla nel router significherebbe che
l'agente non ce l'ha, o che esiste due volte.

La risposta è un elenco di giorni, ognuno con il totale ore (stringa, come ogni `Decimal` di questo
progetto), il dettaglio per deal, le attività e le fatture in scadenza; più le attività senza
scadenza, fuori dai giorni. Un giorno senza niente **non** è nella risposta: il mese lo ricostruisce
il client, che sa già quanti giorni ha, e una risposta con trentuno oggetti vuoti sarebbe rumore su
ogni richiesta.

Il mese arriva come `YYYY-MM` e viene interpretato con l'orologio unico del progetto
(`clock.today_local`). Nessun `date.today()`: la scansione AST dello slice 6B fallisce la build se
qualcuno ne introduce un secondo, e un mese calcolato in UTC sposta il primo e l'ultimo giorno di
chi lavora a Roma.

---

## 7. La superficie MCP

Le attività sono operazioni ordinarie e reversibili, quindi stanno sulla superficie di default:
`create_attivita`, `update_attivita`, `complete_attivita`, `cancel_attivita`, `list_attivita`,
`get_attivita`, `archive_attivita`, `restore_attivita`. Nessuna entra nell'elenco dei divieti dello
slice 3 §11: nessuna consuma un numero, tocca il registro fiscale o cambia una tariffa.

`get_calendar_month` è la stessa lettura della web app. Serve perché la domanda «cosa scade questa
settimana» è esattamente quella che si fa a un agente, e perché senza di essa l'agente dovrebbe
ricostruirla da tre elenchi.

---

## 8. Il posto nell'interfaccia

`/app/calendario`, e nel menu laterale **subito sotto Home**, in `TOP_LEVEL`: è una vista
trasversale come la Home, non appartiene né a «Vendite» né ad «Amministrazione».

La griglia è mensile, lunedì-domenica, con i giorni fuori dal mese in grigio e il giorno corrente
marcato. Ogni casella mostra il totale ore e i marcatori delle scadenze; il click apre il pannello
del giorno. Nessuna vista settimanale: la settimana esiste già, è la griglia di `/app/ore`, e
duplicarla qui sarebbe una seconda schermata da tenere allineata.

---

## 9. Criteri di accettazione

1. `/app/calendario` è nel menu sotto Home e apre sul mese corrente; le frecce cambiano mese e
   l'URL porta il mese, così un link a un mese è un link.
2. Un giorno con ore mostra il totale e, aperto, il dettaglio per deal.
3. «Giornata» crea una riga di 8 ore sul deal scelto; la riga compare nel registro di `/app/ore` e
   nel P&L del deal, perché è la stessa riga.
4. «Nuova scadenza» crea un'attività su quel giorno; completarla la marca come fatta con la data di
   oggi; annullarla la chiude senza cancellarla.
5. Una fattura emessa non incassata compare nel giorno della sua scadenza, con il numero e
   l'importo, e il click porta alla fattura. Dal calendario non si può cambiare quella data.
6. Un'attività senza scadenza compare nella sezione «senza scadenza» e in nessun giorno.
7. Una chiusura di periodo rifiuta la creazione di ore in quel mese dal calendario con lo stesso
   messaggio del registro: il rifiuto vive nel servizio.
8. Il mese si legge in una sola richiesta; il calendario di un mese vuoto non è un errore.
