# PigroCRM — Slice 6: Dashboard, ricerca globale, automazioni, prompt MCP

**Data:** 2026-08-20
**Stato:** da approvare
**Prerequisiti:** slice 1 in `main`; slice 2 (documenti, offerte, template); slice 3 (fatture);
slice 4 (ore, costi, P&L), **entrambe le metà 4A e 4B**; slice 5 (Gmail e landing, che sposta
l'applicazione sotto `/app/`). Le dipendenze sono verificate al §2, non assunte.

**Ambito:** tre dashboard — commerciale, economica, operativa — la ricerca globale, due automazioni,
e i prompt MCP contestuali.

---

## 1. Perché questo slice esiste, e perché è il più facile da sbagliare

È l'ultimo slice, e non per stanchezza: è l'unico che **non produce dati propri**. Consuma quelli
degli altri cinque. Il ciclo dichiarato nello slice 1 — *Contatto → Cliente → Deal → Offerta →
Lavoro → Time Tracking → Fattura → Analisi economica* — ha tutti gli anelli; questo slice è il posto
da cui si guarda la catena intera.

Ed è per la stessa ragione il più facile da sbagliare. Una dashboard che somma da sé i suoi numeri è
**una seconda fonte di verità**, e una seconda fonte di verità su un margine è peggio dell'assenza
del margine: chi legge un numero sbagliato agisce, chi non legge nessun numero chiede. Lo slice 4 ha
deciso che il ricavo *è* la fattura, che il deal è l'unità del conto economico, che le spese generali
non si ripartiscono e che la tariffa si congela sulla riga. Ogni volta che una dashboard rifà uno di
quei calcoli, quelle decisioni valgono per metà: valgono nella pagina che le ha implementate e non
nella pagina che le ha reinterpretate.

Questo documento è quindi in gran parte un documento di **provenienza**: per ogni cifra, quale
servizio la possiede e quali righe ci stanno dietro. Il §3 fissa la regola; i §4-6 la applicano cifra
per cifra.

C'è una seconda ragione per cui questo slice è delicato, e sta in due residui che sono precisamente i
suoi: la ricerca oggi è `ilike '%termine%'` senza indice (**R6**) e **l'ordinamento promesso dal §7
dello slice 1 non esiste in nessuno dei due adapter** (**R9**). Una ricerca globale costruita sopra
entrambi sarebbe una funzionalità che diventa inutilizzabile esattamente quando l'archivio diventa
interessante. Il §8 li chiude, per le entità che tocca, con la misura che lo dimostra.

---

## 2. Cosa questo slice pretende dagli slice precedenti

Da verificare **prima** di pianificare. Ogni riga è stata cercata nel codice consegnato, non assunta.

| Prerequisito | Da dove | Se manca |
|---|---|---|
| `AnalyticsService.get_period_pnl` / `get_deal_pnl` / `get_budget_vs_actual` | Slice 4 §11 | La dashboard economica non esiste. È il servizio che possiede **tutti** i suoi numeri |
| `InvoiceService` con `stato`, `stato_pagamento`, `data_scadenza`, `imponibile`, `totale` | Slice 3 §8.1 | Niente fatturato, niente da incassare, niente scaduto |
| `time_entries` con `data`, `ore`, `fatturabile`, `invoice_line_id` | Slice 4 §4.1 | La dashboard operativa perde metà delle sue righe |
| `period_locks` e i campi `periodo_chiuso` / `voci_scritte_in_ritardo` nei report | Slice 4 §6.4, §14.2 | La dashboard non può dire se un numero può ancora muoversi, che è metà del suo valore |
| `documents.tipo='offerta'` con `stato` e `OFFER_TRANSITIONS` | Slice 2 §4.1, `documents/service.py:50` | Le automazioni del §9 non hanno trigger |
| `pipeline_stages.tipo` e `code` | Slice 1 §5.4, R11 | Le automazioni non sanno cos'è «vinto» senza fare match sul nome, che è esattamente ciò che `tipo` esiste per evitare |
| **Una sessione per chiamata sul server MCP** (cura di **R1**) | È un task del piano dello slice 4, non più un residuo da decidere | §11.3: questo slice **ne dipende**, e non ha un ripiego |
| **A14 chiuso** (`exclude_unset=True`) | Slice 4 §9.2, §12 | La ricerca aggiunge parametri di ordinamento a schemi di lista; un contratto di aggiornamento a metà strada fra due convenzioni è la condizione peggiore in cui toccarli |
| Il fuso dell'emittente, come deciso dallo slice 3 §6.2 per `data_emissione` | Slice 3 | §4.1: `deals.chiuso_il` è una data di calendario e deve usare **lo stesso** meccanismo, non un secondo |
| L'app servita sotto `/app/` | Slice 5 §9.4 | Le rotte del §13 sono scritte nella forma post-slice-5 |

Due fatti sul codice già spedito, che questo slice eredita e non deve scoprire implementando:

- **`AppShell` non ha nessun header.** Lo slice 1 §10.1 descriveva «header con breadcrumb e ricerca»;
  `apps/web/src/components/AppShell.tsx` consegna sidebar più area contenuto e nient'altro. La
  ricerca globale non si aggiunge a un header esistente: **l'header è parte di questo slice** (§13).
- **`apps/web/src/routes/app/index.tsx` è un segnaposto che nomina questo slice**: «La dashboard con
  i grafici arriva nello slice 6». Quel file viene sostituito, non modificato.

---

## 3. La regola che tiene in piedi lo slice: nessuna cifra nasce qui

**Ogni cifra mostrata su una dashboard è una di queste due cose, e nient'altro:**

1. **restituita alla lettera dal servizio che possiede il dato** — `AnalyticsService`,
   `InvoiceService`, `TimeEntryService` — con lo stesso nome e lo stesso valore, senza riformattarne
   il significato;
2. **un `COUNT` o un `SUM` su righe di una sola tabella**, scritto nel repository di quella tabella
   — anche quando la tabella appartiene a un altro slice: l'aggregato sulle ore vive in
   `TimeEntryRepository`, non in un modulo di dashboard.

E una precisazione che serve, perché i segnali del §6.2 sarebbero altrimenti fuori regola: **un
`COUNT` può attraversare una join, un `SUM` no.** Contare i deal che hanno una fattura emessa
richiede di guardare due tabelle e non produce nessuna cifra di denaro; sommare importi attraverso
una join è il modo classico di contare due volte la stessa riga, e su un margine non si scopre
guardando il totale. Un conteggio su join vive nel repository dell'entità **contata** — quella che
compare nell'elenco del drill-through — e non ha aritmetica dentro.

Non esiste una terza forma. In particolare **nessuna divisione, nessun prodotto e nessuna
sottrazione fra grandezze prese da due servizi diversi**: se un numero del genere serve, appartiene
al servizio che possiede i dati da cui deriva, e va aggiunto là.

Ci sono **due eccezioni, e sono elencate qui** perché un'eccezione non elencata è una regola che non
vale. Entrambe vivono in `deals/repository.py`, entrambe combinano solo colonne di `deals`, e
nessuna delle due è denaro incassato:

- il **valore ponderato di pipeline** (§4), prodotto di `valore_previsto` e `probabilita`,
  etichettato *stima* in ogni punto in cui compare e mai sommato al fatturato;
- il **tasso di conversione** (§4), rapporto fra due conteggi delle stesse righe.

**Conseguenza sull'architettura.** `DashboardService` (nuovo, in `packages/core/src/pigrocrm/core/dashboard/`)
è un servizio di **composizione**: risolve l'autorizzazione, apre una transazione, chiama servizi e
repository e mette insieme il risultato. Non contiene aritmetica. Chiama i **servizi** per le cifre
che qualcun altro possiede già, e i **repository** per gli aggregati che definisce (i conteggi di
pipeline, il feed di attività, i segnali del §6.2).

Perché i repository e non i servizi, per quegli aggregati: un servizio esiste per possedere
autorizzazione, transazione e regole di business, e questi aggregati non ne hanno nessuna oltre a
`deleted_at IS NULL`. Aggiungere `pipeline_summary` a `DealService` creerebbe **due percorsi
raggiungibili da un agente** per lo stesso numero — il tool del dominio deal e il tool della
dashboard — cioè esattamente la duplicazione che questo slice esiste per non introdurre.

Il test di architettura cresce di due clausole, scelte perché sono **verificabili sull'AST senza
inferenza di tipo** — una regola che richiede di sapere che una variabile è un `Decimal` non è una
regola che un test può applicare:

1. nessun modulo sotto `core/dashboard/` **importa `Decimal`**;
2. nessun modulo sotto `core/dashboard/` contiene un nodo `BinOp` con `*`, `/` o `-`, e la lista
   delle eccezioni è **vuota**.

Non è eleganza: è il modo di rendere la regola sopra un fatto della build invece di un'intenzione di
questo documento. Un servizio di composizione che non può sottrarre non può inventare un margine.

---

## 4. Dashboard commerciale

Snapshot della pipeline più due misure di periodo. Non tocca fatture, non tocca ore: legge `deals`,
`pipeline_stages` e `documents`. È la dashboard che funziona anche se lo slice 3 slittasse (§17).

| Cifra | Sorgente esatta | Note |
|---|---|---|
| Deal aperti per stage: numero e `Σ valore_previsto` | `DealRepository.pipeline_summary`: `deals` con `deleted_at IS NULL` e stage con `tipo='open'`, `GROUP BY pipeline_stage_id` | I deal con `valore_previsto IS NULL` sono **contati** e mostrati a parte come «senza valore», mai sommati come zero |
| **Valore ponderato (stima)** | `Σ ROUND(valore_previsto × probabilita / 100, 2)` sulle stesse righe, `ROUND_HALF_UP`, somma di valori già arrotondati | L'unica eccezione del §3. Etichettata *stima*, in una colonna con un'intestazione diversa da qualunque cifra di fatturato |
| Deal vinti / persi nel periodo | `DealRepository.closed_in_period`: `chiuso_il` dentro l'intervallo, stage `tipo IN ('won','lost')` | §4.1 |
| Tasso di conversione | `vinti / (vinti + persi)`, arrotondato a 2 decimali, **`null` se il denominatore è 0** | Zero per cento significa «ho perso tutto»; nessun deal chiuso significa un'altra cosa. Stessa regola dello slice 4 §7.1 sul margine percentuale |
| Valore vinto nel periodo | `Σ valore_previsto` dei deal vinti nel periodo | **Non è fatturato** e non è confrontabile con esso: è il valore che il deal *dichiarava*. Il fatturato di quei deal sta nella dashboard economica, e le due cifre stanno su due pagine per questa ragione |
| Offerte inviate in attesa | `documents` con `tipo='offerta'`, `stato='inviata'`, `deleted_at IS NULL`, con l'età in giorni da `stato_dal` | §4.1 |
| Chiusure previste entro 30 giorni | `deals` aperti con `data_chiusura_prevista` nell'intervallo | Colonna esistente dallo slice 1 |
| Offerte accettate con il deal non vinto | §6.2 | È il segnale che collauda l'automazione A1, e sta qui perché non richiede fatture |

Il periodo è **sempre nell'URL** (`?da=&a=`), con default il mese in corso e preset trimestre/anno.
Uno screenshot o un link condiviso di una dashboard senza periodo esplicito è un numero senza
unità di misura.

### 4.1 Le due colonne che mancano, e perché sono due colonne e non una query

Due cifre della tabella sopra hanno una dimensione temporale che **il modello dati non registra**:
«vinti nel periodo» e «da quanti giorni quest'offerta è ferma». La sola traccia oggi è `activities`.

| Colonna nuova | Su | Scritta da | Tipo |
|---|---|---|---|
| `chiuso_il` | `deals` | `DealService.move_stage`, quando lo stage di destinazione ha `tipo != 'open'`; azzerata quando si torna a un `open` | `Date` |
| `stato_dal` | `documents` | `DocumentService.set_offer_state`, unico scrittore di `documents.stato` | `Date` |

Sono `Date` e non `timestamptz`, contro la convenzione generale dello slice 1 §5, per la ragione
precisa dello slice 3 §6.2: **una data che determina in quale periodo cade una cifra non è un
istante.** Tutti i filtri di periodo di questo slice cadono così su colonne `Date` —
`invoices.data_emissione`, `costs.data`, `time_entries.data`, `chiuso_il` — e nessun confronto misto
esiste. Il calcolo del giorno di calendario usa **lo stesso** meccanismo di fuso che lo slice 3 §6.2
impone a `data_emissione`, non un secondo: due orologi diversi nello stesso prodotto sono un bug che
si manifesta il 31 dicembre.

**Perché non si legge dalla timeline.** `DealService.move_stage` registra un'activity
`stage_changed` con payload `{"from": <nome>, "to": <nome>}` — i **nomi** degli stage, che l'utente
è libero di rinominare. Dedurne «quando questo deal è stato vinto» significa fare match su una
stringa mutabile, cioè precisamente ciò che `pipeline_stages.tipo` e `code` esistono per evitare
(slice 1 §5.4, R11). Una colonna è più economica di un errore silenzioso su una serie storica.

**E qui c'è un'asimmetria che decide il backfill.** Per i **documenti** la timeline è affidabile: il
payload di `state_changed` porta `{"da": "inviata", "a": "accettata"}`, e quelli sono **letterali di
`OfferState`**, non testo dell'utente. Quindi:

- `documents.stato_dal` **si backfilla** in migrazione, dall'`occurred_at` dell'ultima activity
  `state_changed` di quel documento;
- `deals.chiuso_il` **non si backfilla**, e resta `NULL` per tutte le righe precedenti. Le dashboard
  di periodo escludono le righe con `chiuso_il IS NULL` e **lo dichiarano** («N deal chiusi prima
  dell'introduzione di questa misura non sono attribuibili a un periodo»), invece di contarli come
  zero o di attribuirli al mese sbagliato.

Dedurre il resto sarebbe indovinare, e un tasso di conversione indovinato è la peggiore delle cifre:
plausibile e sbagliata.

---

## 5. Dashboard economica

Qui non c'è **nessun** aggregato nuovo. Ogni cifra viene da `AnalyticsService` o da `InvoiceService`.

| Cifra | Sorgente esatta | Perché così |
|---|---|---|
| **Fatturato (imponibile, emesso)** | `AnalyticsService.get_period_pnl(da, a).ricavi` | §5.1 |
| Costi diretti · Costo del lavoro · Margine lordo · Margine % | le omonime righe di `get_period_pnl` | Slice 4 §7.1. Il margine è mostrato in **due colonne**, *deal chiusi* e *deal in corso*, come richiede lo slice 4 §7.4, e la cifra riportabile è la prima. Non esiste una casella con la loro somma |
| Spese generali del periodo | riga propria di `get_period_pnl` | Non ripartite su nessun deal (slice 4 §7.4). La dashboard non le distribuisce: le mostra dove sono |
| Valore maturato non fatturato · ore fatturabili non fatturate · ore senza tariffa | righe informative di `get_period_pnl` | Slice 4 §7.1, §5.1. Compaiono sotto un'intestazione diversa da «ricavi» e non entrano in nessun margine. **Sono le righe del periodo**, e il §6 mostra le stesse grandezze come arretrato senza periodo: due numeri diversi con lo stesso nome sono il modo più rapido di perdere la fiducia di chi legge, quindi l'etichetta porta lo scope — «nel periodo» qui, «in totale» là — e le due cifre non sono mai affiancate |
| **Da incassare** | `InvoiceService`: `Σ totale` su `tipo='fattura'`, `stato='emessa'`, `stato_pagamento='da_incassare'`, `deleted_at IS NULL` | §5.2 |
| **Scaduto** | come sopra, con `data_scadenza < oggi` | §5.2 |
| Fatture emesse nel periodo (numero) | `COUNT` sullo stesso predicato del fatturato | |
| Periodo chiuso? · voci scritte in ritardo | i campi che `get_period_pnl` restituisce già (slice 4 §6.4) | È la sola informazione che dice a chi legge se il numero può ancora muoversi. Mostrata accanto al totale, non in una nota a piè di pagina |

### 5.1 Cosa significa «fatturato», e perché non ci sono tre significati

Lo slice 3 distingue **emesso** da **incassato**; lo slice 4 §7.1 ha scelto emesso, e ha scelto
`imponibile` e non `totale`, con tre ragioni scritte. Questa dashboard **non introduce un terzo
significato**: `fatturato = get_period_pnl().ricavi`, cioè
`Σ invoices.imponibile` su `tipo='fattura'`, `stato='emessa'`, `deleted_at IS NULL`, attribuito al
periodo da `data_emissione`.

L'etichetta a schermo è **«Fatturato (imponibile, emesso)»** per esteso, non «Fatturato». Tre parole
in più su una card sono il prezzo per non avere due utenti che leggono la stessa cifra come due cose
diverse. E il criterio 1 del §16 verifica che la cifra segua `imponibile` e **falliscano** se segue
`totale`, con un profilo `RF01` sintetico in cui le due divergono — lo stesso profilo che lo slice 3
§14.8 introduce nelle fixture proprio per rendere osservabili le regole che il forfettario non
esercita.

### 5.2 «Da incassare» non è un ricavo, e per questo usa `totale`

È l'unica cifra di questa pagina che non viene dal P&L, e usa una colonna diversa: **`totale`, non
`imponibile`**. La ragione è che non è la stessa grandezza. Un ricavo è quanto hai prodotto; un
credito è quanto devi ricevere in banca, e quello che devi ricevere comprende l'IVA, che è denaro
che incassi per conto dello Stato. Sotto forfettario le due cifre coincidono e la differenza non è
osservabile — è la stessa condizione, e la stessa risposta, dello slice 4 §7.1: si scrive oggi
perché oggi non si vede.

Conseguenze rese esplicite, perché sono il modo in cui una cifra del genere fa danno:

- «Da incassare» **non entra in nessun margine** e non compare nella stessa riga di totale del
  fatturato;
- non è un conto economico per cassa, che lo slice 4 §13 dichiara fuori ambito nominando il campo
  che lo produrrebbe (`data_incasso`). Questa dashboard **non** lo produce;
- «Scaduto» è un sottoinsieme di «Da incassare», mostrato come tale (indentato sotto), non come una
  seconda voce sommabile.

### 5.3 Cosa è deliberatamente assente

| Assente | Perché |
|---|---|
| La **stima fiscale** (imponibile, sostitutiva, contributi, netto) | Lo slice 4 §11 ragione 4 la classifica come il dato più sensibile del prodotto. Una dashboard è la schermata che più facilmente finisce in uno screenshot o in una condivisione schermo. Resta dov'è: `/app/analisi/fiscale`, ruolo `admin`, con l'etichetta «stima» in testa. La dashboard mostra un link, non un numero |
| Il margine di un singolo deal in cima alla pagina | Il P&L per deal esiste già (tab «Economia», slice 4 §15). Ripeterne uno «in evidenza» richiederebbe una regola per scegliere quale, cioè una classifica dei clienti per margine — che è la funzionalità che lo slice 4 §13 rifiuta di abilitare per inerzia |
| Qualunque confronto con lo stesso periodo dell'anno precedente | Richiede di decidere cosa fare quando il periodo precedente è parzialmente scritto o chiuso, e la risposta giusta dipende da `period_locks` in un modo che nessuno ha ancora esercitato. Un confronto sbagliato è peggio di nessun confronto |

---

## 6. Dashboard operativa

Risponde a una domanda sola: **cosa devo fare adesso.** Nessun totale economico nuovo.

| Cifra | Sorgente esatta |
|---|---|
| Ore registrate nella settimana corrente, per giorno | `TimeEntryRepository`, `SUM(ore) GROUP BY data` sulle righe non cancellate della settimana |
| **Giorni senza nessuna ora nella settimana corrente** | lo stesso aggregato, letto al contrario |
| Arretrato da fatturare: ore fatturabili non fatturate (numero) e valore maturato | `AnalyticsService.get_unbilled_backlog()`, §6.3 |
| Voci senza tariffa | lo stesso metodo (slice 4 §5.1 le nomina già come cifra a sé) |
| Attività recenti (feed globale) | `ActivityRepository.recent(limit)`, nuovo, §6.1 |
| Segnali di incoerenza | §6.2 |

Questa dashboard **non prende un periodo**: le sue cifre sono la settimana corrente e un arretrato,
che sono le due cose che non hanno senso al passato. È anche la ragione per cui l'arretrato non può
venire da `get_period_pnl`, che è per definizione di periodo (§6.3).

Il secondo rigo non è statistica: è il fallimento vero che lo slice 4 §13 nomina rifiutando il
cronometro — *«non ho mai inserito martedì»*. È l'unica cifra di questo slice che ha una
controparte agentica diretta: il prompt `ore-da-registrare` del §10.

### 6.1 Il feed globale ha bisogno di un indice che non c'è

`ActivityRepository.timeline` interroga per entità e ordina già correttamente
(`occurred_at DESC, id DESC`) — R9 **non** riguarda la timeline. Ma l'unico indice è
`ix_activities_entity (entity_type, entity_id, occurred_at)`, che un feed globale ordinato per data
non può usare: la colonna di ordinamento è la terza. Serve
`ix_activities_recent (occurred_at DESC, id DESC)`, e `ActivityRepository.recent(limit)` accanto a
`timeline`. Il feed è limitato a 50 righe e non paginato: uno storico completo delle attività è la
timeline dell'entità, che esiste già.

### 6.2 I segnali di incoerenza — cioè le automazioni che non si possono fare

Quattro conteggi, ognuno con un collegamento all'elenco che li contiene. Sono qui perché ognuno
descrive uno stato che **un'automazione avrebbe potuto correggere**, e il §9.3 spiega perché in tre
casi su quattro l'automazione non si può scrivere senza entrare in una transazione che non la vuole.

| Segnale | Predicato | Dove compare | Cosa suggerisce |
|---|---|---|---|
| **Offerta accettata, deal non vinto** | `documents` `tipo='offerta'` `stato='accettata'` il cui deal ha stage `tipo != 'won'` | dashboard **commerciale** | È il caso in cui l'automazione A1 (§9) **non è scattata**: perché disattivata, o perché fallita con una ragione. È il collaudo permanente dell'automazione, e per questo sta sulla dashboard che non dipende dalle fatture — arriva insieme all'automazione, non uno slice dopo |
| Fatturato ma non vinto | deal con almeno una `invoice` `emessa` e stage `tipo='open'` | operativa | Non si fattura un lavoro che non si è vinto: quasi sempre è lo stage rimasto indietro |
| Vinto ma da fatturare | deal `won` con ore `fatturabile=true` e `invoice_line_id IS NULL` | operativa | È lo stato `da fatturare` che lo slice 4 §7.3 già definisce, contato qui |
| Scaduto e non incassato | `invoices` `emessa`, `da_incassare`, `data_scadenza < oggi` | operativa | È la lista candidate dei solleciti dello slice 5 §7.1, contata. Il conteggio **non** manda niente |

Nessuno dei quattro è memorizzato, nessuno è un flag su una riga: sono predicati. Un segnale
memorizzato è la seconda fonte di verità del §1 in una forma travestita.

### 6.3 L'arretrato è di `AnalyticsService`, non di questa pagina

`get_period_pnl` restituisce ore non fatturate **del periodo**; qui serve il totale, senza periodo,
perché «quanto ho da fatturare» non è una domanda su marzo. E il suo valore in euro è
`Σ ROUND(ore × tariffa_applicata, 2)` — un prodotto fra due colonne, cioè una forma che il §3
proibisce a un modulo di dashboard.

Quindi lo slice aggiunge **un metodo a `AnalyticsService`**, che è il servizio che possiede quella
formula dallo slice 4 §7.3: `get_unbilled_backlog()`, che restituisce ore fatturabili non fatturate,
valore maturato corrispondente, e conteggio delle voci senza tariffa. La dashboard lo chiama e
riporta i suoi campi alla lettera.

Conseguenza sul test di architettura dello slice 4 §11, da rispettare e non da aggirare: un metodo
pubblico nuovo su `AnalyticsService` vuole un tool oppure una voce nella lista di esclusione. Ha un
tool (`get_unbilled_backlog`, §11.1), quindi **la lista di esclusione dello slice 4 resta
esattamente i suoi dieci nomi**. È l'esito giusto: l'arretrato è la cifra su cui un agente può
essere più utile, ed è in sola lettura.

---

## 7. Freschezza e costo

Una dashboard che aggrega fatture, ore e deal a ogni caricamento è, se costruita male, una pila di
scansioni sequenziali. Le tre alternative erano: calcolo su richiesta, cache con una scadenza
visibile, riepilogo materializzato. La decisione, con il suo motivo:

**Calcolo su richiesta, nessun riepilogo materializzato, nessuna cache lato server.**

Un riepilogo materializzato — una tabella `dashboard_summary`, o una vista materializzata da
rinfrescare — è **la seconda fonte di verità del §1 resa permanente**. Nel momento in cui esiste,
esiste una domanda a cui il prodotto non sa rispondere: quando il totale materializzato e la somma
delle fatture divergono, quale dei due è la verità? La risposta corretta («le fatture») rende il
riepilogo inutile; la risposta comoda («il riepilogo») rende il registro fiscale un'opinione. Il
progetto non ha nemmeno un processo worker che potrebbe rinfrescarlo (slice 5 §4.5 e §10 lo dicono
in chiaro), quindi il rinfresco cadrebbe su una richiesta HTTP utente, che è il calcolo su richiesta
con un passaggio in più e un modo in più di sbagliare.

### 7.1 Una dashboard, un endpoint, una transazione, un istante

**Ogni dashboard è un solo endpoint e una sola transazione, in `REPEATABLE READ`.** Non un endpoint
per card.

La ragione è la coerenza interna, e non è teorica: sei query in sei transazioni possono mostrare una
fattura dentro il fatturato e fuori dal conteggio delle fatture, perché è stata emessa fra la terza
e la quarta. Un utente che somma a mano due card e non ottiene la terza smette di fidarsi di tutte
e tre — e ha ragione.

**E una transazione sola non basta.** In `READ COMMITTED`, che è il default di Postgres e quindi ciò
che si ottiene senza dirlo, **ogni istruzione prende il proprio snapshot**: sei query dentro la
stessa transazione possono vedere sei stati diversi esattamente come sei transazioni. La proprietà
che serve la dà `REPEATABLE READ`, dove lo snapshot è preso una volta all'inizio. La transazione è
di sola lettura, quindi non paga il prezzo che di solito si associa a quel livello: un errore di
serializzazione può colpire solo chi scrive, e qui nessuno scrive.

La risposta porta `calcolato_alle`, che è il `transaction_timestamp()` di **quella** transazione, e
il `periodo` normalizzato.

Il costo accettato: nessun rendering parziale. Una cifra lenta rallenta la pagina intera. È
sopportabile perché le query sono poche e il periodo è sempre vincolato (§4), ed è il prezzo della
proprietà per cui questa pagina esiste.

### 7.2 La cache sta nel browser, e la sua età si vede

- `staleTime` di **60 secondi** per la query di dashboard in TanStack Query, che è già l'unico strato
  dati del frontend (slice 1 §10.2).
- L'età si **mostra**: «aggiornato 2 minuti fa», derivato da `calcolato_alle`, più un pulsante di
  ricalcolo. Un numero senza età è un numero che l'utente crede istantaneo.
- Le chiavi di invalidazione sono quelle che `lib/query.ts` già espone: emettere una fattura,
  registrare ore o spostare un deal invalida la dashboard, come già invalida la lista che ha toccato.

**Cosa succede quando il numero in cache e i dati sottostanti divergono.** Divergeranno: è una
cache. La risposta di progetto è che **non possono divergere nel merito, solo nel tempo**, e
poggia su due proprietà:

1. **Nessuna dashboard scrive niente.** Non c'è nessuno stato da riparare, nessuna riconciliazione,
   nessun «ricalcola i totali». La divergenza è per costruzione soltanto anzianità.
2. **La card e il suo drill-through sono la stessa query, non due calcoli.** Cliccando la cifra si
   arriva all'elenco filtrato **con lo stesso predicato**, che riesegue dal vivo. Se i due numeri
   differiscono, la differenza è l'anzianità della risposta di dashboard, vince l'elenco e la card
   si aggiorna. Non c'è nessun caso in cui i due possano dire cose diverse sugli stessi dati.

La seconda proprietà è vera solo se il predicato è letteralmente lo stesso, quindi è un criterio
eseguibile e non una promessa: il criterio 2 del §16 confronta il numero della card con il conteggio
del suo drill-through, su dati identici, per ogni card che ha un collegamento.

### 7.3 Il budget, misurato

- Ogni endpoint di dashboard sotto **300 ms** sul corpus di riferimento del §16 (10 anni di lavoro
  di uno studio da cinque persone: 2.000 deal, 5.000 fatture, 60.000 voci di ore, 3.000 costi).
- **Nessun `Seq Scan` su `invoices`, `time_entries`, `costs` e `activities`**, verificato con
  `EXPLAIN (ANALYZE, BUFFERS)` in CI e non a occhio: sono le tabelle che crescono con l'uso, e sono
  quelle su cui la scansione è il difetto. **Su `deals` l'asserzione non si fa**, e la ragione va
  scritta o qualcuno la aggiungerà per simmetria e avrà un test rosso senza un difetto: duemila deal
  stanno in poche pagine, e su una tabella così Postgres sceglie la scansione perché *è* il piano più
  economico. Là il criterio è la latenza, più il fatto che il predicato porti sempre il periodo e
  `deleted_at IS NULL`.
- Gli indici che servono e non ci sono: `ix_activities_recent` (§6.1), gli indici parziali su
  `deleted_at IS NULL` per le tabelle che questo slice interroga (cura parziale di **R7**), e gli
  indici trigram del §8.3. Tutti gli indici di forma non banale vanno aggiunti a
  `HAND_MAINTAINED_INDEXES` in `packages/core/tests/test_migrations.py`, che documenta già che
  l'autogenerate di Alembic omette in silenzio esattamente queste forme.

---

## 8. Ricerca globale

Una palette stile Spotlight, `Cmd/Ctrl+K` da qualunque schermata. E il vincolo che decide tutto il
resto: **una ricerca che restituisce risultati parziali senza dirlo è peggio di nessuna ricerca**,
perché insegna a concludere «non c'è» da «non l'ho trovato».

### 8.1 Cosa si cerca, e cosa no

| Entità | Campi |
|---|---|
| Cliente | `ragione_sociale`, `partita_iva`, `codice_fiscale`, `email` |
| Persona | `nome`, `cognome`, `email` |
| Deal | `nome` |
| Documento | `titolo` |
| Fattura | `causale`; più `(anno, numero)` quando il termine ha la forma di un numero fiscale (`2026/7`, `7/2026`, `7`), servito dall'indice unico `uq_invoices_anno_numero` che lo slice 3 §3 crea già |

Fuori, con la ragione:

| Fuori | Perché |
|---|---|
| **Corpi delle email** (`gmail_messages.body_text`, slice 5 §5.4) | Tre ragioni indipendenti. Sono fino a 256 KB per riga, e indicizzarli è un ordine di costo diverso. Contengono le parole del cliente su terzi, e una palette globale le tirerebbe fuori dal loro contesto. E la prosa vuole `tsvector`, non i trigrammi (§8.2): sarebbe un secondo motore di ricerca, non un campo in più. La via di estensione è una colonna `tsvector` su `body_text` con il suo indice, nominata qui come confine |
| Descrizioni di ore e costi | Alto volume, testo interno, valore di ritrovamento basso. Chi cerca un'ora cerca un deal e poi guarda le sue ore |
| Note (`customers.note`, `deals.note`) | Markdown lungo: stessa argomentazione dei corpi email, in piccolo. Se un giorno servirà, servirà con `tsvector` |
| Valori dei campi custom | Sono JSONB con l'indice GIN per la **containment**, non per il testo. Cercarci dentro per sottostringa richiede un indice per chiave, cioè una decisione su quali chiavi — che è configurazione, ed è un altro slice |

### 8.2 Perché i trigrammi e non il full-text

`to_tsvector` con GIN è lo strumento canonico, ed è quello sbagliato **qui**. Un dizionario stemma
le parole e indicizza token interi: `ross` non trova `Rossi`, e un frammento di partita IVA
(`0123456`) non è una parola in nessuna lingua. `websearch_to_tsquery` con `:*` copre il prefisso e
non il mezzo. Ma la metà di ciò che si cerca in un CRM è un frammento in mezzo a un nome proprio o
a un codice.

`pg_trgm` fa esattamente questo — sottostringhe su nomi e codici, con una misura di somiglianza da
usare per l'ordinamento — ed è la cura che il residuo **R6** già nomina. E ha una proprietà che vale
per il §8.6: **non c'è nessun indice da rinfrescare.** Un indice GIN trigram è sull'espressione della
colonna, aggiornato dalla transazione che scrive la riga. Non esiste lo stato «indice non
aggiornato», quindi non esiste la schermata che deve spiegarlo. Una colonna `tsvector`
materializzata, invece, sarebbe stata una seconda copia del dato — cioè il §1 di nuovo.

Una nota non ovvia, da non riscoprire con un test rosso: `similarity()` di `pg_trgm` normalizza a
minuscolo internamente, quindi `similarity('Rossi', 'rossi') = 1`. Non serve un
`lower()` nell'espressione dell'indice, e aggiungerlo creerebbe un indice che `ILIKE` sulla colonna
grezza non può usare.

### 8.3 R6: gli indici, e i due caratteri

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX ix_customers_ragione_sociale_trgm ON customers USING gin (ragione_sociale gin_trgm_ops)
  WHERE deleted_at IS NULL;
-- e così per customers.partita_iva, codice_fiscale, email; people.nome, cognome, email;
-- deals.nome; documents.titolo; invoices.causale
```

**Parziali su `deleted_at IS NULL`**, perché è la condizione che ogni ricerca porta: l'indice è più
piccolo e chiude R7 nell'area che questo slice tocca.

Tre conseguenze da gestire, non da scoprire:

1. **L'estensione va creata in migrazione, e se non si può il deploy deve fallire.** `pg_trgm` è
   un'estensione contrib: sull'immagine `postgres:17-alpine` del compose l'utente `pigrocrm` è
   creato dall'immagine come superuser e `CREATE EXTENSION` funziona; su un Postgres gestito
   dipende dall'allowlist del fornitore. Le migrazioni girano all'avvio dell'API (slice 1 §12),
   quindi il fallimento è **rumoroso al deploy**, che è quello che serve: l'alternativa — l'app che
   parte e scansiona sequenzialmente in silenzio — è il difetto che stiamo curando, con un indice in
   meno. Una riga nel runbook nomina il privilegio richiesto, sul modello di B6.
2. **La forma dell'indice va nella lista fatta a mano.** `HAND_MAINTAINED_INDEXES` in
   `packages/core/tests/test_migrations.py` documenta già che l'autogenerate omette i GIN e gli
   indici su espressione. Dieci indici trigram omessi in silenzio sono dieci scansioni sequenziali
   che tornano un mese dopo.
3. **Da verificare nel primo task, non da assumere.** Il predicato consegnato è
   `col.ilike(pattern, escape="\\")`, che SQLAlchemy rende come `col ILIKE :p ESCAPE '\'`. Postgres
   pianifica `LIKE ... ESCAPE` come `like_escape(pattern, escape)` dentro l'operatore `~~*`, e con
   entrambi gli argomenti costanti il constant folding produce un pattern costante che l'indice
   trigram serve. **Va confermato con `EXPLAIN`.** Se non regge, il ripiego è togliere la clausola
   `ESCAPE`: il backslash è già l'escape predefinito di Postgres, come la docstring di `escape_like`
   dice esplicitamente, quindi la clausola è ridondante e la sua rimozione non cambia semantica. È
   una riga, ma va decisa con la misura davanti.

**E il caso sotto i tre caratteri.** Un indice trigram non può servire un pattern da cui non si
estrae nessun trigramma: per un termine di uno o due caratteri, `ILIKE '%ab%'` torna a essere una
scansione. Quindi:

- la **ricerca globale** richiede almeno **3 caratteri**, e sotto quella soglia non interroga: la
  palette scrive «continua a scrivere» invece di eseguire. Non è una limitazione arbitraria — un
  termine di due caratteri su 50.000 clienti restituisce migliaia di righe, cioè comunque nessuna
  risposta;
- gli **endpoint di lista esistenti** non cambiano semantica: con l'indice in piedi diventano veloci
  da 3 caratteri in su e restano quello che sono sotto. Il residuo resta, ridotto, e va scritto:
  *una ricerca di uno o due caratteri su un endpoint di lista è ancora una scansione.* Ha un limite
  superiore noto (il `limit` massimo è 200) e nessun percorso agentico o di palette la raggiunge.

### 8.4 R9: l'ordinamento che non esiste, e il cursore che deve cambiare

Il §7 dello slice 1 promette «paginazione cursor-based, ordinamento e filtri». R9 misura che
l'ordinamento non esiste in **nessuno** dei due adapter: ogni `list()` ordina per `id`, che con UUID
v7 significa ordine di creazione. La paginazione keyset è costruita su quel fatto
(`WHERE id > :cursor ORDER BY id`).

Questo slice non può ignorarlo, perché il «vedi tutti» della palette (§8.5) atterra su quegli
elenchi, e un elenco di risultati di ricerca in ordine di creazione non è un elenco di risultati.

**Cosa si fa, e cos'è il limite del rimedio:**

- Gli endpoint di lista di `customers`, `people`, `deals` e `documents` accettano
  `sort` — una **whitelist** per entità (`creato_il`, `aggiornato_il`, e la colonna identificativa:
  `ragione_sociale`, `cognome`, `nome`, `titolo`) — e `dir` (`asc`/`desc`).
- La paginazione resta **keyset**, non passa a offset: la paginazione a offset rilegge righe e salta
  righe sotto inserimento concorrente, ed è la ragione per cui lo slice 1 ha scelto il keyset. Ma un
  keyset su una colonna non unica richiede un **cursore composito**: `cursor` diventa una stringa
  opaca che codifica `(valore_di_ordinamento, id)`, e il predicato è la consueta comparazione
  lessicografica sulla coppia.
- **È un cambio di contratto**: `cursor: UUID` diventa `cursor: str`. È contenuto — il frontend
  rimanda `next_cursor` alla lettera senza interpretarlo — e la rottura la trova il type check sul
  client generato da OpenAPI, che è esattamente il meccanismo che lo slice 1 §10.2 ha messo lì per
  questo caso.
- Le colonne di `sort` devono essere indicizzate, o l'ordinamento è un `sort` in memoria su tutta la
  tabella. Gli indici trigram non servono a questo: servono indici B-tree su
  `(colonna, id)` per ogni coppia ammessa. La whitelist è corta **per questo motivo**, non per
  prudenza.
- Una colonna di ordinamento **nullable** — `people.cognome` lo è — vuole `NULLS LAST` nella
  clausola e un cursore capace di rappresentare il nullo, o la prima pagina che finisce dentro i
  nulli non ha un valore da cui ripartire. È la seconda ragione per cui il cursore è opaco e non un
  valore grezzo in query string: una stringa vuota in un parametro di URL non è distinguibile da un
  nullo, e su questa distinzione si perdono righe.
- R9 si chiude **per queste quattro entità**. `time_entries` e `costs` nascono già ordinate (slice 4
  §12); `invoices` ha i suoi filtri (slice 3 §11). Il residuo generale su tutte le altre superfici
  resta aperto, e va scritto invece di dichiarare chiuso ciò che è chiuso per quattro tabelle.

### 8.5 Come si ordinano i risultati della ricerca

Il punteggio è una formula scritta, non un'euristica, perché l'ordine di una palette è una
funzionalità e va poter essere verificato:

```
punteggio_campo = 1.00  se lower(campo) = lower(termine)          (esatto)
                = 0.80  se lower(campo) inizia con lower(termine)  (prefisso)
                = 0.60 × similarity(campo, termine)                (sottostringa)

peso_campo      = 1.00  campo identificativo (ragione_sociale, nome+cognome, deal.nome, titolo)
                = 1.00  partita_iva, codice_fiscale, (anno, numero)   -- un match su un codice è voluto
                = 0.90  email
                = 0.80  causale

punteggio_riga  = max(peso_campo × punteggio_campo) sui campi che hanno prodotto un match
```

Righe sotto **0.20** si scartano: la coda dei trigrammi è rumore, e mostrare rumore in una palette
insegna a ignorarla.

Ordinamento: `punteggio DESC`, poi `aggiornato_il DESC` (a pari punteggio, ciò che si è toccato più
recentemente è più probabilmente ciò che si cerca), poi `id DESC`. **Il terzo criterio esiste perché
l'ordine deve essere totale**: senza, due esecuzioni sulla stessa base dati possono restituire lo
stesso insieme in ordine diverso, e il criterio 4 del §16 lo verifica su venti esecuzioni.

**La palette non pagina**, e questa è una decisione, non un'omissione: mostra fino a **5 risultati
per classe di entità** più il conteggio reale di quella classe, e un «vedi tutti» che porta
all'elenco di quell'entità filtrato con **lo stesso termine**, dove la paginazione è il keyset del
§8.4. Un ranking calcolato non è una colonna su cui si possa fare keyset, e paginare per offset su
un punteggio significa righe ripetute e righe saltate. Così invece: **il ranking dove non si pagina,
la paginazione dove non si fa ranking.**

Il conteggio è esatto fino a 200 e poi dichiarato come «oltre 200» (`SELECT count(*)` su una
sottoquery con `LIMIT 201`): esatto quando l'esattezza serve, economico quando non serve, e mai una
bugia.

### 8.6 I tre stati dell'interfaccia, che devono essere tre

| Stato | Cosa mostra | Perché è distinto |
|---|---|---|
| Nessun risultato | «Nessun risultato per *termine*» | È un'informazione: quel dato non c'è |
| Risultati troncati | i primi 5 per classe, **il conteggio**, e «vedi tutti» | È l'antidoto al difetto che questa sezione esiste per non commettere: l'utente sa che sta guardando una parte, e sa quanto è il tutto |
| Ricerca non disponibile | il messaggio dell'errore e nessun elenco | Un elenco vuoto disegnato dopo un errore **è** una risposta sbagliata: dice «non c'è» quando la verità è «non lo so» |

Il terzo stato è quello che si dimentica, quindi è un criterio: con il database che rifiuta la
query, la palette mostra lo stato d'errore e **la stringa «Nessun risultato» non compare nel DOM**
(§16.5).

Il degrado sotto i 3 caratteri (§8.3) è un quarto stato, ma non è un errore: è un invito
(«continua a scrivere»), e non esegue nessuna query.

---

## 9. Automazioni

Il brief è esplicito sul fatto che devono restare semplici, e nomina tre cose: *un'offerta accettata
sposta il deal a vinto, una fattura aggiorna il ricavo del deal, le ore registrate aggiornano il
P&L.* Il lavoro di questo paragrafo è dire quali delle tre sono automazioni, e la risposta non è
tre.

### 9.1 Due delle tre sono già derivazioni, e implementarle sarebbe un bug

| Voce del brief | Stato | Perché |
|---|---|---|
| «Un'offerta accettata sposta il deal a vinto» | **è un'automazione** | Cambia uno stato che nessuno deriva: `deals.pipeline_stage_id`. §9.2 |
| «Una fattura aggiorna il ricavo del deal» | **già fatto, come derivazione** | Lo slice 4 §7.1 definisce il ricavo come `Σ invoices.imponibile` letto a interrogazione. Non esiste nessuna colonna «ricavo del deal» da aggiornare, e **crearla sarebbe esattamente la seconda fonte di verità del §1**: due settimane dopo, una fattura annullata a mano in SQL lascerebbe un ricavo che non corrisponde a nessun documento |
| «Le ore registrate aggiornano il P&L» | **già fatto, come derivazione** | Il costo del lavoro è `Σ ROUND(ore × costo_applicato, 2)` a interrogazione (slice 4 §7.1). Registrare un'ora *è* l'aggiornamento del P&L; non c'è un secondo passo |

La frase del brief descriveva un **flusso di dati**, e gli slice 3 e 4 quel flusso l'hanno
implementato come derivazione — che è la forma migliore, perché una derivazione non può divergere.
Scriverle come automazioni oggi significherebbe smontare quella scelta. Va detto qui, e non
lasciato a chi legge il brief nell'ordine sbagliato.

### 9.2 Le due regole vere

Un solo punto di trigger: `DocumentService.set_offer_state`, che è già l'**unico scrittore** di
`documents.stato`.

| Regola | Trigger | Effetto | Attiva per difetto |
|---|---|---|---|
| **A1** — offerta accettata → deal vinto | transizione `inviata → accettata` su un documento con `deal_id` | il deal passa allo stage con `code='vinto'`, o all'unico con `tipo='won'` | sì |
| **A2** — offerta inviata → il deal avanza | transizione `bozza → inviata` | il deal passa allo stage `code='offerta'` **solo se** la sua `posizione` attuale è inferiore | sì |

Tre dettagli che decidono se queste regole sono utili o fastidiose:

- **A2 non torna mai indietro.** Il confronto su `posizione` fa sì che un deal già in Negoziazione
  non retroceda perché è stata mandata una seconda offerta. Un'automazione che sposta all'indietro
  viene disattivata dall'utente il primo giorno.
- **Un'offerta rifiutata non sposta niente.** Sembra la simmetria naturale di A1 e non lo è: a
  un'offerta rifiutata segue quasi sempre una revisione, e marcare il deal `lost` costringerebbe a
  riaprirlo per dire la verità — cioè a corrompere la pipeline per salvare la cronologia, che è
  esattamente il fallimento che lo slice 4 §4.3 rifiuta per le ore su un deal chiuso. Si scrive
  un'activity e basta.
- **Lo stage bersaglio si risolve per `code`, poi per `tipo`, poi si rinuncia.** Mai per nome: è la
  ragione per cui `pipeline_stages.code` e `tipo` esistono. Se non c'è nessuno stage `won`, o se ce
  ne sono due senza `code`, l'automazione **non indovina**: non fa nulla e registra la ragione
  (§9.5). Per **A2 il ripiego su `tipo` non esiste**, perché lo stage «Offerta» è `open` come tutti
  gli altri: si risolve solo per `code='offerta'`, e in sua assenza A2 non fa nulla e lo dice. Sono
  due regole con la stessa forma e due risoluzioni diverse, e confonderle produrrebbe un deal
  spostato in uno stage aperto qualsiasi.

### 9.3 Dentro la transazione del trigger — ed è questa la risposta a «cosa succede se fallisce a metà»

**Entrambe le regole girano nella stessa transazione dell'azione che le ha attivate.** Quindi la
domanda «cosa succede se un'automazione fallisce a metà» ha una risposta strutturale: **non esiste
un mezzo.** O l'offerta è accettata e il deal è spostato, o nessuna delle due cose è vera.

Questo è possibile per A1 e A2 e **non** per un'automazione agganciata all'emissione di una fattura,
e la differenza va capita perché è il criterio con cui questo slice ha scelto cosa automatizzare:

- `set_offer_state` è una transazione ordinaria di CRM. Aggiungerle un partecipante costa un lock in
  più su una riga di `deals`.
- `InvoiceService.issue()` è la transazione con il lock di riga del contatore (slice 3 §3), quella
  che «meno di ogni altra vuole nuovi partecipanti» — parole dello slice 3, che lo slice 4 §10.1 ha
  già rispettato scrivendo il legame ore↔riga fuori da essa. Un'automazione dentro `issue()`
  allungherebbe la sezione critica della numerazione fiscale per spostare un deal; un'automazione
  dopo il commit sarebbe un secondo passo che può fallire da solo, cioè esattamente il «mezzo» che
  qui non esiste.

**Da qui la regola di progetto di questo slice, dichiarata perché è ciò che tiene piccola la
funzionalità: un'automazione che non può girare nella transazione del suo trigger non diventa
un'automazione. Diventa un segnale di dashboard (§6.2).** «Fatturato ma non vinto» è quel segnale, e
al posto di un meccanismo con uno stato di ripresa costa un predicato.

**Come si aggancia, nel dettaglio.** Non con un hook implicito: `set_offer_state` chiama
esplicitamente `AutomationRunner.on_offer_state_changed(document, previous, actor)`, e l'ordine
dentro il metodo è:

1. mutazione di `documents.stato` e `stato_dal`;
2. **runner** — che muta il deal e registra la propria activity;
3. `self.activities.record(...)` del documento;
4. `commit`.

L'ordine non è cosmetico. La docstring di `ActivityService.record` prescrive che sia «l'ultima cosa
che tocca la sessione prima del commit del chiamante» e che **non** sia seguita da una chiamata a un
altro servizio che committa per conto proprio. Il runner sta prima, e non committa mai.

E per non committare, il runner non può chiamare `DealService.move_stage`, che committa e registra
per conto suo (produrrebbe anche una seconda voce di timeline per lo stesso spostamento). Quindi
questo slice introduce **una sola nuova convenzione**, e la rende meccanica:

> Un servizio può esporre un metodo `*_in_transaction(...)` che muta, non registra, non committa e
> non controlla l'autorizzazione. Il test di architettura verifica che tali metodi siano chiamati
> **solo** da `core/automations/`.

Qui è `DealService.set_stage_in_transaction(deal, stage)`, che riusa `_settle_probability` — così
l'invariante «vinto al 60%» resta irraggiungibile anche per questa via, che è l'unica ragione per
cui quella funzione è a livello di modulo.

L'**autorizzazione** è quella del trigger: `set_offer_state` chiama già
`actor.require_write`, e un `readonly` non arriva al runner. Il runner non ri-autorizza e non
eleva: se ci riuscisse, accettare un'offerta diventerebbe una via per scrivere su un deal che
l'attore non potrebbe toccare.

Un'ultima distinzione, perché «catturare le eccezioni» è il posto in cui questo genere di codice
mente: il runner **assorbe** soltanto un elenco dichiarato di condizioni di dominio — stage
bersaglio assente o ambiguo, deal già nello stato bersaglio, regola disattivata — le registra, e
lascia proseguire il trigger. Qualunque altra eccezione **propaga e fa rollback di tutto**: un
database che non riesce a scrivere non è un'automazione che non è scattata, ed è l'unico caso in cui
è giusto che l'utente non veda accettata la sua offerta.

### 9.4 L'idempotenza è ereditata, non aggiunta

Non c'è nessuna tabella di registro delle esecuzioni, e non serve. Tre proprietà, già in albero:

1. **Il trigger è irripetibile per costruzione.** `OFFER_TRANSITIONS` (`documents/service.py:50`)
   dà `"accettata": frozenset()`: lo stato accettato è terminale, quindi la transizione
   `inviata → accettata` avviene **al massimo una volta per documento**. Non è disciplina, è la
   macchina a stati consegnata dallo slice 2.
2. **L'effetto è convergente.** Il bersaglio è uno stato, non un incremento: due offerte accettate
   sullo stesso deal producono un primo spostamento e un secondo no-op registrato come
   `già_nello_stato`. Un'automazione che sommasse qualcosa avrebbe bisogno del registro; una che
   assegna uno stato no.
3. **Atomicità con il trigger** (§9.3): non esiste il caso «scattata ma non registrata».

Un registro delle esecuzioni sarebbe quindi una tabella la cui unica funzione è rispondere a una
domanda a cui `activities` risponde meglio — che è lo stesso ragionamento con cui lo slice 3 §7.1 ha
rifiutato di storicizzare `fiscal_profile` e lo slice 4 §5.2 le tariffe.

### 9.5 Un'automazione che nessuno può osservare è indistinguibile da un bug

Quattro superfici, e la quarta è quella che di solito manca:

1. **Una voce di timeline per esecuzione**, sul deal: `kind='automazione.stage_spostato'`,
   `actor_type='system'` — la distinzione che lo slice 1 §5.8 chiama non cosmetica — e payload con
   `regola`, `documento_id`, `da`, `a`, `attivata_da` (l'id dell'attore del trigger). `Actor.system()`
   esiste già e porta `id=None`, ed è per questo che l'attore del trigger sta nel payload: la
   timeline dice «l'ha fatto il sistema» **e** «perché tu hai accettato quell'offerta». Una sola
   voce per lo spostamento, non due (§9.3).
2. **Un ritorno immediato nell'interfaccia**: il dialogo di cambio stato dell'offerta mostra cos'altro
   è successo («Il deal è stato spostato in Vinto»), con `sonner`, che è già in albero.
3. **Una pagina `/app/impostazioni/automazioni`**: le due regole, il loro interruttore, e le ultime
   20 esecuzioni con esito — che è una query su `activities` per `kind`, non una tabella nuova.
4. **La voce per la non-esecuzione.** `kind='automazione.non_eseguita'`, con `motivo` fra
   `stage_bersaglio_assente`, `stage_bersaglio_ambiguo`, `già_nello_stato`, `regola_disattivata`.
   Senza questa, «non è scattata» e «non doveva scattare» sono la stessa schermata vuota. E il
   segnale «offerta accettata, deal non vinto» del §6.2 è il suo controllo incrociato permanente: se
   l'automazione tace, il conteggio parla.

### 9.6 Configurazione

`automation_config`, riga singola come `emitter_profile` e `fiscal_profile`: due booleani, default
entrambi `true`. Modificabile da `admin`, e ogni modifica scrive un'activity — la chiusura di **R5**
per questa tabella, con lo stesso argomento dello slice 3 §7.1: cambiare cosa il sistema farà da
solo ai dati futuri è di un ordine di gravità diverso dal rinominare uno stage.

Nessun costruttore di flussi, nessuna condizione configurabile, nessun secondo effetto per regola
(§15). Due booleani sono la superficie di configurazione, ed è deliberato: la semplicità richiesta
dal brief è una proprietà da difendere, non un punto di partenza da cui crescere.

---

## 10. Prompt MCP contestuali

I prompt sono una primitiva **distinta** dai tool, e la distinzione decide a cosa servono:

| | Tool | Prompt |
|---|---|---|
| Chi lo invoca | il **modello**, quando decide che gli serve | l'**utente**, scegliendolo da un menu |
| Cosa restituisce | un dato | dei **messaggi**, cioè l'inizio di una conversazione |
| Dove sta il giudizio | nel modello | **nel prompt**: «segnala solo scostamenti oltre il 10%» |

Verificato sull'SDK installato (`mcp==2.0.0`, non assunto dalla documentazione):
`MCPServer.prompt()` registra una funzione, gli argomenti si inferiscono dalla firma come per i tool,
la funzione può ricevere il `Context` — quindi **può leggere il database come un tool** — e un
messaggio può contenere sia testo sia un blocco `{"type": "resource", ...}`.

Da qui la regola su come questi prompt portano il contesto, che è una regola perché il §11.1 non
aggiunge nessuna risorsa nuova: **il contesto viaggia come testo Markdown dentro il messaggio**, ed
è un blocco di risorsa **solo quando la risorsa esiste già** — cioè `customer://{id}` dello slice 1
§8.4, in `stato-cliente`. Un blocco di risorsa ha bisogno di un URI, e inventare
`dashboard://commerciale?da=…` per infilarcelo significherebbe aggiungere una risorsa senza dirlo.
In entrambe le forme la proprietà che conta resta: il contesto **arriva dentro il prompt**, invece
che dipendere dal fatto che il modello vada a prenderselo.

È il motivo per cui questi quattro sono prompt e non tool: ognuno è la composizione di più letture
**più una postura su come leggerle**. Un tool che restituisse anche quella postura infilerebbe
istruzioni in un risultato di dati, che è la forma di un'iniezione; e il modello dovrebbe indovinare
di doverlo chiamare, mentre qui è l'umano che lo sceglie e vede cosa gli è stato allegato.

| Prompt | Argomenti | Cosa porta dentro | A cosa serve |
|---|---|---|---|
| `revisione-pipeline` | `da`, `a` (opzionali, default mese) | la dashboard commerciale (§4) come testo, più le offerte in attesa con la loro età | La revisione settimanale. La postura: chiedere dei deal fermi, non riassumere quelli che si muovono |
| `chiusura-mese` | `anno`, `mese` | il P&L di periodo (§5) invariato, le ore fatturabili non fatturate, le fatture scadute, `periodo_chiuso` e `voci_scritte_in_ritardo` | La lista di cose da fare prima di chiudere. **Nessuna cifra fiscale** (§10.1) |
| `stato-cliente` | `customer_id` | la risorsa `customer://{id}` che esiste già dallo slice 1 §8.4, come blocco di risorsa, più i deal aperti, le fatture non incassate e l'ultima attività come testo | Il briefing prima di una telefonata. È l'unico prompt che incorpora una risorsa, perché è l'unico per cui la risorsa esiste |
| `ore-da-registrare` | `settimana` (opzionale) | i giorni della settimana senza nessuna ora (§6) e i deal su cui si è lavorato di recente | È il prompt più utile del prodotto: attacca il «martedì mai inserito» che lo slice 4 §13 nomina, e finisce chiedendo all'utente cosa ha fatto per poi chiamare `log_time` — che è un tool che l'agente **ha** (slice 4 §11) |

### 10.1 Due divieti sui prompt, e sono divieti

- **Nessun prompt contiene la stima fiscale.** Lo slice 4 §11 ragione 4 la tiene fuori dall'MCP
  perché un PAT senza scope (R10) è indistinguibile da un accesso completo. Un prompt che la
  incorporasse aggirerebbe quella decisione senza chiamare il tool che non esiste. Il criterio 10
  del §16 lo verifica per nome di campo, non per intenzione.
- **Nessun prompt incorpora dati che il tool corrispondente non restituirebbe.** Un prompt è
  un'altra confezione degli stessi permessi, non una scorciatoia attraverso di essi.

---

## 11. Superficie MCP e API

### 11.1 I tool

La regola non negoziabile resta: **i tool MCP e i router FastAPI chiamano gli stessi servizi
in-process**, e il test di architettura lo verifica.

| Operazione | API | MCP |
|---|---|---|
| `get_commercial_dashboard(da, a)` | sì | sì |
| `get_economic_dashboard(da, a)` | sì | sì |
| `get_operational_dashboard()` | sì | sì |
| `search_everything(termine, limite)` | sì | sì |
| `get_unbilled_backlog()` | sì | sì |
| `describe_automations()` | sì | sì |
| `update_automation_config(...)` | sì, `admin` | **no** |

**Le tre dashboard sono esposte anche via MCP**, e non è per simmetria: la loro forma è già la
composizione senza aritmetica del §3, quindi il tool restituisce **le stesse cifre dello stesso
servizio proprietario**, mai una seconda versione. Non aggiungerle costringerebbe un agente a fare
sei letture e a sommarle da sé, che è il modo più diretto di ottenere la seconda fonte di verità
per un'altra strada.

`update_automation_config` è l'unica esclusione, per la ragione 2 dello slice 4 §11: cambia cosa il
sistema farà a dati futuri senza un umano nel ciclo. Il test di architettura di slice 3 §11 e slice 4
§11 cresce di tre servizi — `DashboardService`, `SearchService`, `AutomationConfigService` — e per
questi la lista di esclusione dichiarata deve essere **esattamente** `update_automation_config`. La
lista dello slice 4 resta i suoi dieci nomi: il metodo nuovo su `AnalyticsService` (§6.3) ha il suo
tool.

`describe_automations` restituisce le due regole, il loro stato e le ultime esecuzioni. Le esecuzioni
sono una lettura di `activities` per `kind` — `ActivityRepository.by_kind(kinds, limit)`, nuovo
accanto a `recent` — non una tabella nuova (§9.4).

**Nessuna risorsa nuova.** Una risorsa è indirizzata da un URI; una dashboard è una domanda con un
periodo, e ficcare il periodo in un URI costringerebbe il client a indovinarne la grafia. Un tool con
una firma tipizzata è scopribile. Le risorse esistenti (`customer://`, `person://`, `deal://`, più
gli arricchimenti dello slice 4 §11) restano il modo di far **leggere** prima di far **agire**.

### 11.2 Gli endpoint

```
GET /api/dashboard/commerciale?da=&a=
GET /api/dashboard/economica?da=&a=
GET /api/dashboard/operativa
GET /api/search?q=&limit=
GET /api/analytics/backlog               # get_unbilled_backlog, accanto agli endpoint analytics
                                         #   dello slice 4 perche' il metodo e' di AnalyticsService
GET /api/automation-config        · PUT (admin)
GET /api/automation-runs?limit=          # lettura di activities per kind, non una tabella nuova
```

Più, sugli endpoint di lista già esistenti di `customers`, `people`, `deals`, `documents`: i
parametri `sort` e `dir`, e `cursor` che diventa una stringa opaca (§8.4).

### 11.3 R1: sì, questo slice ne dipende

Il residuo R1 — una sola `Session` SQLAlchemy condivisa da tutte le chiamate del server MCP — **non
è più una decisione da prendere: è un task del piano dello slice 4**, dove `log_time` non può
esistere senza di esso (slice 4 §12, criterio 11). Quando questo slice comincia, la cura è in
`main`, e questo slice **la dà per fatta invece di aggirarla**.

Va scritto comunque, per due ragioni: perché **l'aggregazione in lettura lo peggiora**, e perché se
la cura slittasse i tool di questo slice non devono essere registrati — un dashboard tool su una
sessione condivisa non è una funzionalità degradata, è una cifra sbagliata.

- una query di aggregazione tiene la connessione occupata più a lungo di una `get`, quindi allarga
  la finestra in cui due chiamate si sovrappongono — che è la condizione misurata nella review dello
  slice 1A (10 scritture concorrenti, 0 successi, 0 righe);
- e soprattutto la garanzia del §7.1 — **una dashboard, una transazione, un istante** — è una
  proprietà della sessione. Con una sessione condivisa e nessun confine transazionale per chiamata,
  due dashboard concorrenti possono leggere metà delle proprie cifre dentro la transazione dell'altra
  e produrre un totale che non è mai stato vero in nessun istante. È la seconda fonte di verità del
  §1 generata dall'infrastruttura invece che dal codice, ed è il caso peggiore perché non si vede
  rileggendo il servizio.

---

## 12. Modello dati: il delta

Piccolo, e deve restarlo. Nessuna tabella di riepilogo, nessuna colonna derivata, nessuna cache
persistita.

| Cosa | Dove | Perché |
|---|---|---|
| `chiuso_il` `Date` null | `deals` | §4.1. Nessun backfill |
| `stato_dal` `Date` null | `documents` | §4.1. Backfill dalla timeline in migrazione |
| `automation_config` (riga singola, due booleani) | nuova | §9.6 |
| `pg_trgm` + 10 indici GIN trigram parziali | §8.3 | R6 |
| `ix_activities_recent (occurred_at DESC, id DESC)` | `activities` | §6.1 |
| Indici B-tree `(colonna_di_sort, id)` per la whitelist di `sort` | §8.4 | R9 |
| Indici parziali su `deleted_at IS NULL` per le tabelle interrogate qui | §7.3 | R7, parzialmente |

Nuovi `kind` di `activities`, senza migrazione perché `kind` è un valore aperto per progetto
(slice 1 §5.8): `automazione.stage_spostato` · `automazione.non_eseguita` ·
`automazione.configurazione_modificata`.

Nessun nuovo `entity_type`: le automazioni scrivono sulle entità che già esistono (`deal`,
`document`), che è anche il motivo per cui compaiono nella timeline giusta. Il residuo **R13** non
viene quindi toccato — e va detto, perché è la prima volta in quattro slice che l'estensione in
quattro punti non serve.

---

## 13. Interfaccia

- **L'header, che non esiste.** `AppShell` acquisisce la barra superiore promessa dallo slice 1
  §10.1: breadcrumb a sinistra, **campo di ricerca** al centro con la scorciatoia visibile, azioni a
  destra. Non è un ritocco: è metà del residuo di quella sezione.
- **La palette.** `Cmd/Ctrl+K` da qualunque schermata. Si adotta `cmdk` (il componente `command` di
  shadcn) invece di comporla con `dialog` + `input`: un combobox accessibile — ruoli ARIA,
  `aria-activedescendant`, navigazione da tastiera, annuncio dei risultati a uno screen reader — è
  una delle cose che si scrivono male a mano, e il costo è una dipendenza piccola in un progetto che
  già porta `radix-ui`. I tre stati del §8.6 sono tre rendering distinti, non un elenco vuoto con
  tre messaggi.
- **`/app/` — la dashboard.** Sostituisce il segnaposto che nomina questo slice. Tre schede —
  Commerciale · Economica · Operativa — con il periodo nell'URL. **Nessun ruolo nuovo e nessuna
  regola di autorizzazione nuova**: ogni dashboard è visibile a chi può leggere i servizi da cui
  legge, e lo slice 4 §11 li dà a tutti i ruoli. Un `readonly` vede tutte e tre. L'unica cifra a
  `admin` di quell'area è la stima fiscale, che non sta su nessuna dashboard (§5.3) — inventare qui
  un quarto livello di visibilità significherebbe aggiungere una regola di sicurezza in una
  schermata di lettura, che è il posto in cui nessuno la va a cercare.
- **`/app/impostazioni/automazioni`** — §9.5.
- **Nessun totale calcolato nel browser.** Regola dello slice 4 §6, qui estesa: le dashboard non
  sommano nulla, nemmeno le ore visibili. Il criterio 14 del §16 estende il test sull'AST che lo
  slice 4 §14.4 ha già scritto ai moduli di questo slice.
- **I grafici, senza una libreria di grafici.** Quattro forme: numeri grandi, barre orizzontali
  (larghezze CSS), una sparkline e una tabella. Sono SVG inline e CSS. Le ragioni: una libreria
  costa fra 40 e 100 KB per quattro forme, in un progetto che sulla landing si è dato un budget di
  40 KB totali (slice 5 §9.4); e imporrebbe una tavolozza propria, mentre `tokens.css` è la fonte
  unica del colore e ha dei test dietro. Servono cinque token `--chart-1…5`, ottenuti per
  `color-mix()` dalle cinque tinte esistenti come lo slice 5 §9.3 fa per `--landing-*`, con la
  **stessa** regola meccanica: nessun esadecimale grezzo nel blocco, e il test di contrasto di
  `tokens.test.ts` esteso ai nuovi token. E ogni grafico ha la sua tabella equivalente, perché un
  grafico senza tabella è una cifra che uno screen reader non legge.

---

## 14. Residui che toccano questo slice

| Residuo | Interazione |
|---|---|
| **R6** — ricerca `ilike` senza indice | **È di questo slice.** Chiuso con `pg_trgm` e dieci indici parziali (§8.3), con la misura in CI (§16.3). Resta il caso sotto i tre caratteri sugli endpoint di lista, dichiarato e limitato |
| **R9** — l'ordinamento promesso non esiste | **È di questo slice.** Chiuso per `customers`, `people`, `deals`, `documents`, con cursore composito (§8.4). Aperto per il resto, e scritto così |
| **R1** — sessione MCP condivisa | Non è più aperto come decisione: è un task del piano dello slice 4. Questo slice **ne dipende** e spiega perché l'aggregazione in lettura lo peggiora (§11.3) |
| **R7** — nessun indice parziale su `deleted_at` | Chiuso per le tabelle che questo slice interroga, come effetto degli indici trigram parziali. Il difetto generale resta |
| **R5** — nessun audit per la configurazione | Chiuso per `automation_config` (§9.6), come slice 3 per `fiscal_profile` e slice 4 per le tariffe. Aperto per il resto |
| **R10** — PAT senza scope | È la ragione per cui la stima fiscale non entra in nessun prompt (§10.1). Nessuna chiusura ulteriore qui |
| **B2** — la lista deal non ha debounce | Peggiora qui: la palette interroga a ogni tasto su cinque entità. Il debounce (250 ms) e l'annullamento della richiesta precedente sono **parte** di §8, non un miglioramento successivo |
| **B3** — la Kanban carica anche i deal chiusi | Non peggiora: le dashboard sono paginate e con periodo obbligatorio dall'inizio, come lo slice 4 §12 ha già imposto alla vista margini. Il difetto sulla board resta |
| **A12** — `required` su una checkbox | Non toccato. Nominato perché è l'unico residuo 1B che nessuno slice ha ancora raccolto |
| `pipeline_stages` senza vincolo di unicità su `tipo` | Non è un residuo noto: **emerge qui per la prima volta.** Niente vieta due stage `tipo='won'`. Le automazioni non lo risolvono con una migrazione (romperebbe installazioni esistenti che l'hanno fatto per un motivo): risolvono per `code`, e se restano ambigue non fanno nulla e lo dicono (§9.2) |

---

## 15. Ciò che questo slice **non** fa

| Fuori ambito | Perché |
|---|---|
| **Dashboard configurabili, layout di widget, spostamento di card** | Tre dashboard fisse con cifre giustificate valgono più di una tela vuota. Un layout configurabile richiede una persistenza per utente, una migrazione dei layout a ogni cifra aggiunta, e sposta la decisione «quali numeri contano» dal prodotto all'utente — che è la decisione che questo documento ha appena passato quindici paragrafi a prendere |
| **Report programmati, invii periodici, digest via email** | Non c'è nessun processo worker e non se ne vuole uno (slice 5 §4.5, §10). Un report programmato senza worker è un cron installato a mano dall'operatore che chiama un endpoint: se serve, quell'endpoint è già `GET /api/dashboard/*` |
| **Export** oltre a quello che gli slice 3 e 4 già producono | Il rapporto ore (PDF e XLSX), il PDF e l'XML della fattura esistono. Un CSV di dashboard sarebbe un quarto artefatto con una quarta forma da mantenere, e la cifra che contiene la si legge dalla pagina |
| **Previsioni, forecast, trend, proiezioni** | Lo slice 4 §13 le esclude già. Il valore ponderato di pipeline (§4) **non** è una previsione: non ha dimensione temporale e non estrapola niente, è la moltiplicazione di due colonne che l'utente ha scritto a mano, ed è etichettata *stima* |
| **Costruttore di flussi, regole configurabili, trigger definiti dall'utente** | Il brief chiede automazioni semplici. Due booleani (§9.6) sono la superficie di configurazione. Un costruttore di flussi porta un valutatore di condizioni, un ordine di esecuzione, una semantica dei fallimenti e un modo per fermare un ciclo: quattro meccanismi per un prodotto che ha due regole |
| **Analitiche di terze parti, telemetria, tracciamento del prodotto** | Lo slice 5 §12 lo ha già stabilito per la landing con un budget misurato. Un'app self-hosted che chiama casa è la contraddizione del prodotto |
| **Ricerca nei corpi delle email, nelle note, nei campi custom** | §8.1, con la via di estensione nominata per ognuna |
| **Ricerche salvate, filtri condivisi, avvisi su una ricerca** | Sono configurazione per un utente, in un prodotto single-tenant dove l'utente è quasi sempre uno. La palette e i filtri di lista coprono la domanda |
| **Classifiche: clienti per margine, collaboratori per redditività** | Lo slice 4 §13 rifiuta la seconda per una ragione che vale anche per la prima: è una scelta gestionale, e non si abilita per inerzia perché lo schema lo permette |
| **Conto economico per cassa sulla dashboard** | Slice 4 §13. «Da incassare» è un credito, non un ricavo, e il §5.2 lo tiene separato per costruzione |

---

## 16. Criteri di successo

Eseguibili in CI, non da guardare. Il **corpus di riferimento** — dieci anni di lavoro di uno studio
da cinque persone: 500 clienti, 800 persone, 2.000 deal, 5.000 fatture, 60.000 voci di ore, 3.000
costi — è generato da una fixture e girato su Postgres reale via testcontainers, come tutto il resto
della suite (slice 1 §11). È il corpus dei criteri di dashboard.

Il criterio 3 usa una **variante gonfiata** dello stesso generatore, con ogni tabella cercata a
50.000 righe, e la ragione sta nel criterio stesso: un'asserzione sul piano di esecuzione non
significa niente su una tabella che sta in poche pagine.

1. **Una cifra di dashboard si riconcilia esattamente con il servizio che possiede il dato.**
   `GET /api/dashboard/economica?da=&a=` restituisce un `fatturato` uguale **al centesimo** a
   `AnalyticsService.get_period_pnl(da, a).ricavi`, e uguale a una `SELECT SUM(imponibile) FROM
   invoices WHERE tipo='fattura' AND stato='emessa' AND deleted_at IS NULL AND data_emissione
   BETWEEN …` eseguita come SQL diretto, in un percorso indipendente dal servizio. Confronto su
   `Decimal`, mai su float. Ripetuto con il profilo `RF01` sintetico (slice 3 §14.8) in cui
   `imponibile` e `totale` divergono: la dashboard deve seguire `imponibile`, **e il test deve
   fallire se segue `totale`**. Specularmente, `da_incassare` deve seguire `totale` e il test deve
   fallire se segue `imponibile`: le due grandezze non sono scambiabili (§5.2).
2. **Ogni card coincide con il suo drill-through.** Per ogni cifra della dashboard che ha un
   collegamento, il numero della card è uguale al conteggio delle righe che l'elenco collegato
   restituisce con gli stessi filtri, interrogato indipendentemente. Un solo predicato, due letture.
3. **La ricerca non degenera in una scansione.** Per questo criterio il corpus porta **ogni tabella
   cercata a 50.000 righe** — e la ragione è la stessa che al §7.3 vieta di asserire sul piano di
   `deals`: su una tabella piccola la scansione sequenziale *è* il piano giusto, quindi
   un'asserzione sul piano non significherebbe niente e fallirebbe senza un difetto.
   Su quel corpus, per un termine di 3 caratteri e per uno di 12,
   `EXPLAIN (ANALYZE, BUFFERS)` di ogni ramo di `SearchService` mostra un `Bitmap Index Scan`
   sull'indice trigram e **nessun `Seq Scan`** su `customers`, `people`, `deals`, `documents`,
   `invoices`; la latenza totale dell'endpoint sta sotto **300 ms**. Il test asserisce sul piano, non
   sul tempo soltanto — un tempo buono su una macchina veloce nasconde una scansione. Più:
   `test_migrations` passa con i dieci indici trigram in `HAND_MAINTAINED_INDEXES`, e fallisce
   nominando l'indice mancante se uno viene tolto. E una variante rimuove l'indice a mano e verifica
   che il test **fallisca**: un'asserzione sul piano che passa anche senza l'indice non sta
   misurando l'indice.
4. **L'ordine dei risultati è totale e deterministico.** La stessa base dati e lo stesso termine
   producono un JSON **identico byte per byte** su venti esecuzioni. Un termine che è la partita IVA
   esatta di un cliente lo mette al primo posto; un termine che è un prefisso di una ragione sociale
   la mette sopra una corrispondenza a metà parola.
5. **Nessun risultato parziale silenzioso.** Con 500 righe corrispondenti: la palette mostra 5 per
   classe, il conteggio reale (o «oltre 200»), e il collegamento all'elenco completo. Con il
   database che rifiuta la query: compare lo stato d'errore e la stringa «Nessun risultato» **non è
   presente nel DOM**, verificato con Playwright. Con un termine di 2 caratteri: nessuna richiesta
   HTTP viene emessa.
6. **Una dashboard è un solo istante, e lo snapshot è quello che lo dimostra.** Due asserzioni, e la
   prima da sola non basterebbe: `transaction_timestamp()` è costante per tutta la transazione
   **anche** in `READ COMMITTED`, quindi un test che si fermasse lì passerebbe su una dashboard che
   legge sei stati diversi (§7.1).
   (a) Il livello di isolamento in vigore durante la richiesta è `repeatable read`, letto da
   `SHOW transaction_isolation` sulla stessa connessione.
   (b) Una connessione parallela emette il `COMMIT` di una fattura **fra la prima e la seconda**
   query interna, sincronizzata con una barriera: quella fattura non compare in **nessuna** cifra
   della risposta — né nel fatturato né nel conteggio. Ripetuto con l'isolamento forzato a
   `read committed`, il test **fallisce**, che è ciò che rende l'asserzione (a) significativa invece
   che decorativa.
   (c) `calcolato_alle` è il `transaction_timestamp()` di quella transazione, ed è precedente al
   commit parallelo.
7. **L'automazione è atomica con il suo trigger.** Accettare un'offerta sposta il deal a `vinto`
   nella **stessa** transazione: con un errore iniettato fra l'automazione e il commit, nessuna
   delle due cose risulta avvenuta — l'offerta è ancora `inviata` e il deal è ancora nel suo stage,
   verificato rileggendo entrambe le righe. Con lo stage `vinto` cancellato, accettare **riesce** e
   viene registrato `automazione.non_eseguita` con `motivo='stage_bersaglio_assente'`.
8. **L'automazione è osservabile e non si ripete.** Ogni esecuzione produce **una** activity con
   `actor_type='system'`, `payload.regola` e `payload.attivata_da`, e **una sola** voce di timeline
   per lo spostamento (non due: nessun `stage_changed` parallelo). Una seconda offerta accettata
   sullo stesso deal non cambia niente e registra `motivo='già_nello_stato'`. Un `readonly` che
   tenta il trigger prende `PermissionDenied` e nessuna riga viene toccata.
9. **Disattivata significa disattivata.** Con la regola spenta, accettare un'offerta non muove il
   deal, registra `motivo='regola_disattivata'`, e la modifica della configurazione ha lasciato la
   sua activity.
10. **I prompt esistono, portano il contesto, e non portano il fisco.** `list_prompts()` restituisce
    i quattro prompt con i loro argomenti inferiti dalla firma; il rendering di `chiusura-mese`
    contiene le cifre del P&L **identiche** a quelle di `get_period_pnl` — confrontate valore per
    valore, non a occhio — e **nessun** campo fra `imponibile_fiscale`, `imposta_sostitutiva`,
    `contributi`, `netto_stimato`, verificato per nome di campo su tutti i messaggi resi.
    `stato-cliente` contiene un blocco di risorsa il cui URI è `customer://{id}`, ed è l'**unico**
    prompt che contiene un blocco di risorsa (§10): un test elenca gli URI incorporati da tutti e
    quattro e verifica che non ne esistano di nuovi. `revisione-pipeline` reso su un database vuoto
    produce un messaggio valido, non un'eccezione.
11. **Il divieto MCP è nel build, e la superficie è di sola lettura.** Per ogni metodo pubblico di
    `DashboardService`, `SearchService` e `AutomationConfigService` esiste un tool o il metodo è
    nella lista di esclusione dichiarata, che deve essere **esattamente**
    `update_automation_config`; e la lista dello slice 4 è ancora **esattamente** i suoi dieci nomi,
    perché `get_unbilled_backlog` ha il suo tool (§6.3). Più: il test di architettura verifica che i
    metodi `*_in_transaction` siano chiamati **solo** da `core/automations/` (§9.3), che nessun
    modulo sotto `core/dashboard/` importi `Decimal`, e che nessuno contenga un nodo `BinOp` con
    `*`, `/` o `-` (§3).
12. **Lettura concorrente via MCP.** Dieci `get_economic_dashboard` simultanei su Postgres reale
    restituiscono dieci risposte identiche **a meno di `calcolato_alle`**, che è per costruzione
    l'istante di ciascuna transazione e non può coincidere: un test che pretendesse
    l'uguaglianza byte per byte del JSON intero fallirebbe senza un difetto. Nessun errore di
    sessione, e ogni chiamata ha il proprio `transaction_isolation` corretto. È R1 verificato dal
    lato lettura, e la condizione per cui questi tool esistono.
13. **La paginazione ordinata non perde né ripete righe.** Con `sort=ragione_sociale&dir=asc` e
    inserimenti concorrenti durante la scorsa, l'unione delle pagine non contiene duplicati e
    contiene ogni riga presente sia all'inizio sia alla fine. È la proprietà per cui il keyset è
    stato scelto, e l'unica ragione per cui il cursore composito vale il cambio di contratto.
14. **Nessun numero nasce nel browser.** Il test sull'AST dello slice 4 §14.4 esteso: nessun modulo
    di dashboard applica `Number()`, `parseFloat` o `+` a un campo economico proveniente dall'API.
    E il test di contrasto di `tokens.test.ts` esteso ai token `--chart-*`, che non contengono
    nessun esadecimale grezzo.
15. **Il ciclo completo, dai due adapter.** Claude apre `revisione-pipeline`, legge la dashboard
    commerciale, trova il deal fermo, e con `search_everything` risolve il cliente per un frammento
    di partita IVA; l'umano nell'app accetta l'offerta di quel deal, vede il toast dello
    spostamento, vede la voce `system` nella timeline, e vede il segnale «offerta accettata, deal
    non vinto» scendere di uno; la dashboard economica del mese passa il criterio 1; e il tentativo
    di Claude di cambiare la configurazione delle automazioni non trova nessun tool da chiamare.

---

## 17. Un piano o tre

Giudizio onesto: **una specifica, tre piani**, e vanno eseguiti in quest'ordine.

| Piano | Contenuto | Dipende da |
|---|---|---|
| **6A — Ricerca globale** | §8 per intero: `pg_trgm` e gli indici, `SearchService`, R6 e R9, l'header di `AppShell`, la palette | Slice 1 e 2. **Non** dallo slice 3, 4, 5 |
| **6B — Automazioni, segnali e dashboard commerciale** | §9 per intero, `chiuso_il` e `stato_dal`, `automation_config`, la dashboard commerciale del §4, la pagina di impostazioni | Slice 2 (le offerte sono il trigger). **Non** dallo slice 3 e 4 |
| **6C — Dashboard economica e operativa, prompt MCP** | §5, §6, §10, i tool del §11 | 6A e 6B; **slice 3 e slice 4 (entrambe le metà) in `main`**; slice 5 per le rotte |

Tre ragioni per separarli, non una preferenza estetica.

1. **Il criterio centrale di 6C non è eseguibile senza gli slice 3 e 4.** «Una cifra si riconcilia
   con il servizio che possiede il dato» presuppone che il servizio esista. Tenere un piano solo
   significa che tutti i test della ricerca — che non dipendono da niente di tutto questo — restano
   dietro una dipendenza che non li riguarda.
2. **6A non condivide una riga con 6B**, e 6B non ne condivide una con 6C oltre al servizio di
   composizione. Il taglio non è di dimensione: è dove le dipendenze cambiano.
3. **6A è utile da solo, e lo è subito.** Una ricerca globale che trova un cliente da un frammento
   di partita IVA fa risparmiare tempo ogni settimana, che è il criterio di esistenza che lo slice 1
   §1 pone a ogni funzionalità. È anche il piano che chiude due residui misurati, quindi il valore
   che consegna non dipende dal fatto che il resto dello slice arrivi.

**Ogni piano porta il proprio collaudo.** È il criterio che ha deciso dove tagliare, non una
conseguenza fortunata: il segnale «offerta accettata, deal non vinto» sta sulla dashboard
commerciale e non su quella operativa (§6.2) **proprio** perché è il controllo incrociato
dell'automazione, e un'automazione che arrivasse in 6B con il suo verificatore in 6C sarebbe in
produzione per settimane senza nessuno che sappia se sta funzionando. Allo stesso modo i criteri del
§16 si distribuiscono senza avanzi:

| Piano | Criteri che deve superare |
|---|---|
| 6A | 3, 4, 5, 13 |
| 6B | 7, 8, 9, più **2, 6 e 14 sulla dashboard commerciale** — sono criteri per *ogni* dashboard, e cadono in scadenza con la prima |
| 6C | 1, 10, 11, 12, 15, più 2, 6 e 14 ripetuti sulle due dashboard nuove |

Nessun piano si chiude con criteri che non può eseguire, e nessun criterio resta senza un piano che
lo esegua.

**L'ordine 6A → 6B → 6C non è negoziabile in un punto:** gli indici e il contratto di ordinamento di
6A cambiano la firma degli endpoint di lista, e farlo dopo aver costruito le dashboard significa
toccare due volte gli stessi client generati.

Se gli slice 3 o 4 slittassero, 6A e 6B si rilasciano comunque, e la scheda «Economica» semplicemente
non esiste ancora — cosa che l'utente capisce, a differenza di una scheda che mostra zeri.
