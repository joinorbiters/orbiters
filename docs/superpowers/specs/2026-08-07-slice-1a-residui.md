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

## R5 — Nessun audit trail per configurazione e token

Non esistono voci di timeline per field definition, pipeline stage, utenti e **PAT**. La creazione e la revoca di un token di accesso — cioè l'atto di dare o togliere a un agente le chiavi del CRM — non lasciano alcuna traccia. Sta male accanto allo scopo dichiarato di `activities` nella spec §5.8, e peggio ancora accanto a R10.

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

È la spec §9 come progettata, non un difetto di implementazione. Ma va detto in chiaro: **«dai un token a Claude» oggi significa «dai il tuo account, per sempre, senza traccia di audit» (vedi R5).** Da decidere consapevolmente: scope per token, scadenza, o entrambi.

---

## R11 — La spec non menziona `pipeline_stages.code`

La colonna `code` è stata aggiunta durante la review del Task 9, come identità stabile distinta dal nome visibile — perché `seed_defaults` deduplicava su `nome`, cioè proprio il campo che l'utente è libero di rinominare. La decisione è corretta e implementata; la spec §5.4 non è stata aggiornata.

---

## Nota di metodo

Diciannove difetti reali sono emersi durante l'esecuzione dei 17 task, e **quasi tutti erano nel piano scritto in anticipo**, non negli errori di chi implementava. Sono emersi perché i reviewer hanno *eseguito* invece di leggere: hanno cronometrato l'autenticazione, forgiato token JWT firmati, avviato container Postgres per verificare che i valori accettati si scrivessero davvero, forzato deadlock con SQL grezzo, e riprodotto race con thread reali e barriere.

La famiglia di difetti più ricorrente — sei occorrenze — è sempre la stessa: *un input non validato raggiunge Postgres e torna come eccezione grezza*. Ogni fix aveva coperto solo la forma di colonna che aveva davanti. La review finale l'ha diagnosticata come classe e le ha chiuse insieme, aggiungendo `SafeStr` e i vincoli sugli interi ai vincoli globali del piano.
