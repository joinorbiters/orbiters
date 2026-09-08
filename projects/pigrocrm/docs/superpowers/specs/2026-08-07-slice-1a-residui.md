# Slice 1A — residui noti e decisioni da prendere

**Data:** 2026-08-07
**Stato:** slice 1A completato e integrato in `main` (614 test verdi)
**Scopo:** ciò che sappiamo essere aperto, con l'evidenza che lo dimostra. Non è una lista di desideri: ogni voce è stata riprodotta eseguendola durante la review finale.

---

## R1 — La sessione condivisa del server MCP non è sicura in concorrenza

**Il più serio.** `apps/mcp/src/pigrocrm_mcp/__main__.py` costruisce **una sola** `Session` SQLAlchemy e la passa a `build_server` per tutta la vita del processo. L'SDK MCP però dispatcha le chiamate sincrone **in concorrenza**: due `list_pipeline_stages` si sovrappongono nel tempo di esecuzione, misurato.

Le sessioni SQLAlchemy non sono thread-safe. Misura del reviewer: 10 `create_customer` concorrenti intrecciati a 10 `get_customer` falliti → **0 successi e 0 righe scritte**, con `Method 'rollback()' can't be called here` e `This session is provisioning a new connection; concurrent operations are not permitted`.

**Preesistente**, non introdotto dall'ondata di fix finale: prima era rotto diversamente (1 successo dichiarato, 9 righe scritte davvero). Il `session.rollback()` aggiunto nella guardia ha cambiato il modo di fallire, non la causa.

**Cura:** una sessione per chiamata, come fa l'API per ogni richiesta. `build_server` accetta già un `session_provider` callable, quindi il punto d'aggancio esiste; serve uno scoping con `contextvars` perché `context.session` viene letto fino a quattro volte durante il render di una risorsa. Risolve anche il problema del confine transazionale: oggi non ce n'è uno per chiamata, e una connessione resta idle-in-transaction fra un tool e l'altro.

**Perché non blocca oggi:** un singolo agente locale via stdio emette per lo più chiamate sequenziali. Ma è il primo lavoro da fare sull'MCP.

---

## R2 — Errori pydantic grezzi sugli argomenti che l'SDK valida prima della guardia

`_guard` copre ciò che accade *dentro* un tool, ma l'SDK valida alcuni argomenti **prima** di invocarlo. Restano quindi dump inglesi con link a `errors.pydantic.dev` per: un literal `entity_type` sbagliato (`describe_schema`, `get_timeline`), `changes` o `custom` passati come stringa invece che come oggetto, e un numero al posto di una stringa.

Contraddice la spec §8.2 («gli errori devono essere azionabili da un modello»).

**Cura:** applicare `WithJsonSchema` — già usato in `apps/mcp/src/pigrocrm_mcp/tools/__init__.py` — a ogni scalare stretto, oppure adottare l'hook `intercept_tool_call` dell'SDK, che esiste ma non è usato in questo progetto.

---

## R3 — Un utente disattivato può essere `owner_id` di un deal

`DealService` valida che `owner_id` esista in `users`, ma `UserRepository.get` non filtra `attivo`. La chiave esterna è valida, quindi il database non protesta. È una domanda di prodotto, non un bug: un deal assegnato a chi non lavora più qui è un dato coerente o no?

---

## R4 — Login fallito restituisce 422, non 401

`ValidationFailed` mappa su 422 tramite `STATUS_BY_CODE`, mentre `POST /api/auth/refresh` restituisce correttamente 401 per lo stesso tipo di fallimento. Da decidere **prima** che il client dello slice 1B ci scriva contro, perché cambiarlo dopo significa toccare la gestione degli errori nel frontend.

---

## R5 — Nessun audit trail per configurazione e token — **CHIUSO (2026-09-03)**

Non esistevano voci di timeline per field definition, pipeline stage, utenti e **PAT**. La creazione e la revoca di un token di accesso — cioè l'atto di dare o togliere a un agente le chiavi del CRM — non lasciavano alcuna traccia. Stava male accanto allo scopo dichiarato di `activities` nella spec §5.8, e peggio ancora accanto a R10.

**Chiuso.** Tutte e quattro scrivono ora sulla stessa tabella `activities`: `kind` è una stringa aperta per progetto, quindi non è servita nessuna migrazione e nessun secondo meccanismo. Ogni voce viene scritta per ultima e prima del commit del chiamante, quindi vive o muore con la modifica che registra (`test_a_*_when_its_audit_entry_cannot_be`).

| Entità | `entity_type` | `kind` | Payload |
| --- | --- | --- | --- |
| Field definition | `field_definition` | `created`, `updated`, `archived`, `unarchived` | identità (`entity_type`, `key`, `label`, `field_type`, `required`); su `updated` `changed` + `before`/`after` reali |
| Pipeline stage | `pipeline_stage` | `created` (con `seeded: true` per i default), `updated`, `deleted` | `nome`, `code`, `tipo`; su `updated` `code` + `before`/`after` |
| Utente | `user` | `created`, `updated` | `email`, `ruolo`; su `updated` `before`/`after` di `nome`/`ruolo`/`attivo`. Mai la password né il suo hash |
| PAT | `user` (timeline del proprietario) | `pat_created`, `pat_first_used`, `pat_revoked`, `pat_used_after_revocation` | `token_id`, `nome`. Mai il valore, il prefisso o `token_hash` |

Tre decisioni che vale la pena non dover ricostruire più tardi:

- **I PAT vivono sulla timeline del proprietario**, non su una loro. La domanda che un token solleva riguarda sempre un *account* («chi ha dato a un agente le chiavi di questo, ed è ancora viva?»), e una timeline per token nessuno penserebbe ad aprirla.
- **Solo il primo uso viene registrato**, non ogni `resolve()`: una voce per richiesta raddoppierebbe le scritture dell'API. `last_used_at` risponde già a «è ancora in uso»; quello che mancava era il passaggio da emesso a vivo.
- **`pat_used_after_revocation` è l'unico evento davvero nuovo**: un token revocato ancora presentato è o un agente che nessuno ha riconfigurato o una copia del valore dove il proprietario non voleva. Registrato una volta per revoca, non una per tentativo, altrimenti chi possiede il token morto può far crescere la tabella una riga per richiesta. Un token sconosciuto non registra nulla: non c'è un account a cui appenderlo, e una riga per tentativo trasformerebbe l'audit in un amplificatore per chi tenta.

Lettura: `GET /api/users/{id}/timeline` (amministratori, più il proprietario per il proprio account), `GET /api/field-definitions/{id}/timeline` e `GET /api/pipeline-stages/{id}/timeline` (solo amministratori). **Nessuna delle quattro è raggiungibile da MCP**, e non per un controllo di permessi ma per costruzione: `get_timeline` accetta un `Literal` dei tre domini entità. Un PAT eredita il ruolo pieno del proprietario, quindi un controllo dentro un tool registrato è un controllo che il token di un amministratore supera — e la timeline dell'account è esattamente il registro di quel token.

Resta aperto quanto sotto R10: l'audit dice ora *chi* e *quando*, ma un PAT continua a non avere scope né scadenza.

---

## R6 — Ricerca full-text senza indice

Ogni ricerca da entrambi gli adapter usa `ilike '%termine%'`, che non può usare un indice B-tree: scansione sequenziale. Con poche centinaia di clienti è invisibile; con decine di migliaia no. **Cura:** estensione `pg_trgm` e un indice GIN trigram.

---

## R7 — Nessun indice parziale su `deleted_at`

Ogni query di lista filtra `deleted_at IS NULL`. Un indice parziale su quella condizione è gratuito e mirato.

---

## R8 — Nessun rate limiting sul login; i refresh token non vengono mai potati

Otto password sbagliate consecutive seguite da un successo pulito: nessun blocco, nessun ritardo progressivo. Non richiesto dalla spec, ma la superficie è pubblica.
Separatamente, le righe in `refresh_tokens` si accumulano indefinitamente: serve una potatura delle righe scadute o consumate.

---

## R9 — L'ordinamento promesso dalla spec §7 non esiste

La spec §7 promette «lista con paginazione cursor-based, ordinamento e filtri». Paginazione e filtri ci sono (inclusi quelli sui campi custom, esposti nell'ondata finale). **L'ordinamento non esiste in nessuno dei due adapter.** Metà funzionalità promessa, non mancante del tutto.

---

## R10 — I PAT sono senza scope, ereditano il ruolo pieno e non scadono

Verificato: il PAT di un amministratore può, via REST, elencare gli utenti, **crearne un altro amministratore**, generare altri PAT per sé stesso, modificare le definizioni dei campi e cancellare clienti.

È la spec §9 come progettata, non un difetto di implementazione. Ma va detto in chiaro: **«dai un token a Claude» oggi significa «dai il tuo account, per sempre»**. La parte «senza traccia di audit» non vale più — R5 è chiuso, e l'emissione, il primo uso, la revoca e l'uso dopo la revoca sono ora sulla timeline del proprietario — ma è precisamente per questo che la parte «per sempre, con il ruolo pieno» pesa di più: sappiamo *chi* e *quando*, non *fin dove*. Da decidere consapevolmente: scope per token, scadenza, o entrambi.

---

## R11 — La spec non menziona `pipeline_stages.code`

La colonna `code` è stata aggiunta durante la review del Task 9, come identità stabile distinta dal nome visibile — perché `seed_defaults` deduplicava su `nome`, cioè proprio il campo che l'utente è libero di rinominare. La decisione è corretta e implementata; la spec §5.4 non è stata aggiornata.

---

## Nota di metodo

Diciannove difetti reali sono emersi durante l'esecuzione dei 17 task, e **quasi tutti erano nel piano scritto in anticipo**, non negli errori di chi implementava. Sono emersi perché i reviewer hanno *eseguito* invece di leggere: hanno cronometrato l'autenticazione, forgiato token JWT firmati, avviato container Postgres per verificare che i valori accettati si scrivessero davvero, forzato deadlock con SQL grezzo, e riprodotto race con thread reali e barriere.

La famiglia di difetti più ricorrente — sei occorrenze — è sempre la stessa: *un input non validato raggiunge Postgres e torna come eccezione grezza*. Ogni fix aveva coperto solo la forma di colonna che aveva davanti. La review finale l'ha diagnosticata come classe e le ha chiuse insieme, aggiungendo `SafeStr` e i vincoli sugli interi ai vincoli globali del piano.

---

## R12 — Una partita IVA estera non si può nemmeno salvare

**Trovato scrivendo la spec dello slice 3 (fatturazione), 2026-08-20.**

`customers.partita_iva` è validata `^\d{11}$` — undici cifre, cioè il formato italiano e nient'altro.
Un freelance italiano con un cliente tedesco o francese non può registrarne la partita IVA in nessun
campo nativo.

Non è un dettaglio di validazione: la FatturaPA per un cliente estero richiede un `IdPaese`
diverso e `CodiceDestinatario = XXXXXXX`, quindi la lacuna si propaga direttamente sulla
fatturazione. Lo slice 3 la aggira dichiarando i clienti esteri fuori ambito e rifiutando
l'emissione quando `nazione != 'IT'` — che è onesto ma è una rinuncia, non una soluzione.

**Da decidere:** un `partita_iva` che accetti il formato VIES (prefisso paese più corpo variabile)
con la validazione stretta applicata solo quando `nazione == 'IT'`, oppure un campo separato per
l'identificativo estero. La prima strada è più semplice e non duplica il concetto.

---

## R13 — La promessa che `entity_type` sia «aperto» è inesatta, e costa un'indagine per slice

Sia la spec dello slice 1 (§5.6) sia quella dello slice 2 (§4.1) affermano che aggiungere un nuovo
`entity_type` non richiede modifiche. La colonna sul database è davvero `String(30)` senza vincolo,
quindi **il database** è aperto. Il codice no: `fields/schemas.py` dichiara
`EntityType = Literal["customer", "person", "deal"]`, e ci sono `ENTITY_TYPES` e `CREATE_MODELS` in
`schema_registry.py` più `EntityType` in `apps/web/src/lib/schema.ts`.

Il costo è basso — una riga in quattro posti — ma la promessa è stata verificata e smentita **tre
volte** da tre agenti diversi, una per slice. La formulazione va corretta alla fonte invece di far
ripetere l'indagine: «il database è aperto, il tipo va esteso in quattro punti, nessuna migrazione».

**Aggiornamento del 2026-08-21 — chiuso in parte, e il commento è ora corretto alla fonte.** Lo
slice 2 ha aggiunto `"document"` in tutti e quattro i punti, e `fields/schemas.py` porta adesso un
commento che dice esattamente cosa serve fare («closed by design… widening it means editing here,
`ENTITY_TYPES`/`CREATE_MODELS`, and the frontend type»). Quindi la promessa fuorviante non c'è più.

Ma scrivendo il piano dello slice 3 è emerso un difetto vicino e peggiore: **`native_fields()` è
derivata da `CREATE_MODELS`, e per le fatture la derivazione è sbagliata.** `totale`, `imponibile` e
`numero` sono colonne calcolate che nessuno schema di creazione dichiara, quindi non compaiono fra i
nomi nativi — e A13, che è ancora aperto, non le protegge da una collisione con una chiave custom.
Il piano aggira con un `EXTRA_NATIVE_FIELDS` esplicito e lo dichiara: la derivazione automatica non
è affidabile quando una colonna esiste senza essere scrivibile.

---

## Aggiornamento del 2026-08-20 — R5 e R10 non sono più «da decidere»: bloccano lo slice 5

Scrivendo la spec dello slice 5 (Gmail) è emerso che i due residui sui token non sono più una
questione di igiene rimandabile. Gmail aggiunge una credenziale **di terze parti** sulla casella di
posta di una persona reale. Con i PAT come sono oggi — senza scope, con il ruolo pieno del
proprietario, senza scadenza e senza traccia in audit (R10 e R5) — un token creato per leggere i
deal leggerebbe anche la corrispondenza, e non resterebbe alcuna traccia di chi l'ha creato.

Quindi, **prima** dello slice 5, serve la parte minima di R10 e R5:

- scope sui PAT, con `gmail:*` **spento per difetto**;
- scadenza obbligatoria su qualunque token che porti uno scope Gmail;
- voci di timeline sulla creazione e sulla revoca di un token.

Non è la soluzione completa di R10 — resta aperta la domanda generale su scope e scadenze per tutti
i token — ma è il taglio minimo che impedisce di moltiplicare il problema invece di limitarlo.

## Aggiornamento del 2026-08-20 — la landing è un prerequisito TECNICO di Gmail

Controintuitivo e va scritto, perché cambia l'ordine dei lavori: Google non concede gli scope Gmail
ristretti a un client senza **homepage pubblica e privacy policy**, e un client non verificato resta
in Testing, dove i refresh token degli account consumer **scadono ogni 7 giorni**. La landing non è
la vetrina di Gmail: ne è la condizione di esistenza, e va rilasciata prima.

Conseguenza sul frontend già spedito: `apps/web/src/routes/index.tsx` reindirizza `/` su `/app` e va
rimosso; `deploy/nginx/spa.conf` serve la SPA dalla radice e va portato alla forma con prefisso
`/app/`, con `base: '/app/'` in `vite.config.ts`, la rotta di login spostata e le spec E2E aggiornate.

## Aggiornamento del 2026-08-20 — `customers.email` non è indicizzata

`people.email` lo è, `customers.email` no, e la risoluzione della rilevanza in Gmail interroga
entrambe. Costo basso, va sistemato quando si tocca quell'area.

---

## Aggiornamento del 2026-08-20 — i residui non sono più rimandabili: sono la strada critica

Scrivendo le spec degli slice 4 e 5 è emerso che tre voci di questo documento hanno smesso di essere
«da decidere» e sono diventate **prerequisiti bloccanti**. Non per eleganza: perché senza di esse le
funzionalità di quegli slice sarebbero sbagliate, non solo scomode.

| Residuo | Perché blocca | Chi |
|---|---|---|
| **R1** — sessione SQLAlchemy condivisa sull'MCP | `log_time` è un tool di **scrittura** ed è il centro della superficie agentica dello slice 4. La misura dello slice 1A — 10 scritture concorrenti, 0 successi, 0 righe — è esattamente ciò che accadrebbe. | Slice 4 |
| **A13** — chiave custom che collide con una colonna nativa | Le colonne native dello slice 4 si chiamano `ore`, `data`, `importo`, `descrizione`: sono i nomi che un utente digiterebbe per primo definendo un campo. | Slice 4 |
| **A14** — nessuna grafia azzera una colonna nativa numerica | `ore_preventivate` ha due soli stati raggiungibili, `NULL` e `0.00`, che significano l'opposto per il confronto preventivo/consuntivo — e **solo uno dei due è scrivibile**. Una stima sbagliata resta incastrata e si legge come «zero ore preventivate, sforamento infinito». Lo slice 3 aggirava A14 sostituendo le righe in blocco; qui quella via d'uscita non esiste. | Slice 4 |
| **R10 + R5** — PAT senza scope, senza scadenza, senza audit | Gmail aggiunge una credenziale di terze parti sulla casella di una persona reale: un token creato per leggere i deal leggerebbe la corrispondenza, senza traccia. | Slice 5 |

**Conseguenza sull'ordine dei lavori:** fra lo slice 2 e gli slice 4-5 serve una passata di
irrobustimento sullo slice 1A, che è già in `main`. Non è un rifacimento: sono quattro interventi
circoscritti — una sessione per chiamata sull'MCP, una guardia di collisione in
`FieldDefinitionService.create`, il passaggio da `exclude_none=True` a `exclude_unset=True` sui
servizi, e scope più scadenza più audit sui PAT.

Il terzo è il più invasivo perché cambia il contratto di aggiornamento di tutti i servizi, ed è la
ragione per cui A14 andava affrontato quando era ancora una scomodità.

---

## R14 — `pipeline_stages` non ha un vincolo di unicità su `tipo`

**Trovato scrivendo la spec dello slice 6, 2026-08-21.** Due stati `won` sono legali, e altrettanto
due `lost`. Nessuno dei due documenti sui residui lo diceva: emerge qui per la prima volta, perché è
la prima funzionalità che deve chiedersi *quale* sia lo stato vinto.

Non è un errore di battitura: è che nulla ha mai avuto bisogno di risolvere quella domanda. La
spec dello slice 6 la aggira ordinando per `code`, poi per `tipo`, e rifiutando con un messaggio
esplicito se restano ambigui — senza migrazione, perché rinominare uno stato è un diritto
dell'utente e un vincolo aggiunto ora potrebbe rifiutare dati già presenti.

**Da decidere:** un indice unico parziale su `tipo` dove `tipo IN ('won','lost')`, con una migrazione
che sappia cosa fare se un'installazione ne ha già due.

---

## R15 — Il timeline registra i cambi di stato con i NOMI degli stati, non con gli id

`DealService.move_stage` scrive `{"from": <nome>, "to": <nome>}`. I nomi sono rinominabili
dall'utente, e il payload del timeline è **sanificato, non validato**, quindi qualunque metrica
storica del tipo «quando è stato vinto questo deal» letta da lì è inaffidabile per costruzione.

Lo slice 6 lo risolve aggiungendo `deals.chiuso_il` come dato autoritativo, e **non** fa il backfill
dal timeline per i deal — a differenza di `documents.stato_dal`, che può farlo perché il timeline
delle offerte registra codici e non nomi.

**Da decidere:** arricchire il payload con l'id e il `code` dello stage, in aggiunta al nome. Non
renderebbe il timeline autoritativo — resta sanificato — ma smetterebbe di essere l'unica traccia di
una cosa che nessuno può ricostruire.

---

## Ancora aperto: la promessa dell'header dello slice 1

La spec dello slice 1 (§10.1) promette «header con breadcrumb e ricerca». `AppShell.tsx` non ha
alcun header. La ricerca globale dello slice 6 non ha dove vivere, quindi l'header viene costruito
lì — deciso il 2026-08-21, ed è la collocazione giusta: è la prima funzionalità che ne ha bisogno
per esistere.
