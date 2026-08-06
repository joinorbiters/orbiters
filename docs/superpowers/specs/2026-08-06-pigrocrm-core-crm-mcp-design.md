# PigroCRM — Slice 1: Core CRM + MCP

**Data:** 2026-08-06
**Stato:** approvato in brainstorming, pronto per la pianificazione
**Ambito:** primo slice verticale. Gli slice 2-6 sono elencati per contesto ma hanno spec proprie.

---

## 1. Vision

PigroCRM è un CRM AI-first per freelancer, consulenti e piccole startup italiane, progettato con approccio lean: poche entità, configurazione minima, automazioni prima delle personalizzazioni.

> PigroCRM non è un CRM con l'AI. È un CRM progettato affinché l'AI sia il principale modo di interagire con i dati. L'interfaccia web è un client di riferimento; API e server MCP sono cittadini di prima classe dell'architettura.

Il ciclo che il prodotto copre: **Contatto → Cliente → Deal → Offerta → Lavoro → Time Tracking → Fattura → Analisi economica**, senza cambiare applicazione.

Ogni funzionalità deve rispondere a una domanda: *fa risparmiare tempo ogni settimana?*

---

## 2. Contesto: PigroCRM sostituisce Acme

PigroCRM è il rewrite da zero di **Acme** (https://acme.humancraft.tech, repo `humancraft-tech/acme`), tool interno **attualmente in produzione** per generare offerte e fatture. Il rewrite nasce da limiti strutturali reali, documentati qui sotto.

Il repo pubblico di Acme contiene lo scheletro, i template e il deploy. L'applicazione vive in due file: `website/vite.config.js` (5.485 righe, backend completo) e `website/src/App.jsx` (6.784 righe, frontend completo).

### 2.1 Cosa si riusa

| Asset | Dove sta in Acme | Destinazione |
|---|---|---|
| Pipeline PDF Pandoc + Typst (+ `Dockerfile` con versioni pinnate) | `Dockerfile`, `offer/pandoc-template.typst`, `offer/header.typ`, `offer/invoice-header.typ` | Slice 2 |
| Contenuto legale del template offerta (definizioni, condizioni generali, IP, validità 15gg) | `offer/template-offer.md` | Slice 2 |
| Layout Typst fattura (header, tabella dettaglio, sezione pagamento) | `offer/template-invoice.md` | Slice 3 |
| **Generatore XML FatturaPA FPR12** | `vite.config.js:1720-1889` (`buildInvoiceXml`) | Slice 3 |
| Export XLSX time tracking (`exceljs`) | `vite.config.js:1204` | Slice 4 |
| Integrazione Google Drive (15 funzioni: ensure/find/create folder, upload, update, delete, download) | `vite.config.js:2286-2780` | Slice 2, come storage backend |
| Integrazione Gmail (invio con allegato, solleciti) | `vite.config.js:2455+` | Slice 5 |
| Pipeline CI/CD (lint+build gate → rsync con esclusioni → `docker compose up -d --build` via SSH → nginx idempotente) | `.github/workflows/ci-deploy.yml` | Slice 1, con l'aggiunta dei test come gate |

Il generatore FatturaPA è conoscenza di dominio, non codice: implementa `FPR12`, `TipoDocumento TD01`, `CedentePrestatore`/`CessionarioCommittente`, `DatiBollo/BolloVirtuale`, `DatiRiepilogo` con `Natura N2.2` e `RiferimentoNormativo`, `EsigibilitaIVA I`, `IdTrasmittente`/`ProgressivoInvio`, con escaping XML. Si porta quasi verbatim, correggendo due limiti: `<DettaglioLinee>` è hardcoded a `NumeroLinea 1` (una sola riga), e il regime è fisso `RF19`.

### 2.2 Cosa non si riusa, e perché

**Sintassi placeholder `[NOME_CLIENTE]`.** Collide con la sintassi dei link Markdown, non supporta condizionali né loop, e i valori finiscono non-escapati dentro sorgente Typst — una classe di bug da template injection, testimoniata dal commit `fix(pdf): escape @ and other typst-sensitive chars in placeholders`. Sostituita da `{{var}}` / `{{#if}}` / `{{#each}}` con escaping per contesto di destinazione (slice 2).

**Persistenza su file.** Acme salva `<offerta>.md` + `<offerta>.json` su volume montato: nessuna integrità referenziale, nessuna query, nessuna sicurezza sulla concorrenza. Sostituita da PostgreSQL.

**Backend dentro `vite.config.js`.** L'API è middleware del dev server, e in produzione gira `vite preview`. Non esiste un service layer testabile.

**Frontend monolitico.** `App.jsx` è un unico componente `App()` di ~5.870 righe con 94 `useState` e 7 viste, senza sotto-componenti. Contiene **la logica fiscale**:

```js
const FORFETTARIO_INPS_RATE = 0.2607
const inps = (taxableBase - taxes) * FORFETTARIO_INPS_RATE
```

Coefficiente redditività 67%, imposta sostitutiva 5%, INPS 26,07%, ATECO 62.20.10 — calcolati nel browser: non testabili, non raggiungibili via API, invisibili a un agente MCP. È la giustificazione empirica dell'architettura scelta al §4.

**Auth hardcoded** in `App.jsx` (password nel sorgente di un repo pubblico).

**Attio come CRM.** Acme non è un CRM: è un generatore di documenti appoggiato ad Attio, da cui legge le anagrafiche tirando a indovinare gli slug dei campi fiscali (`vat_number` o `vat` o `piva`; `sdi_code` o `codice_destinatario` o `codice_sdi`). PigroCRM assorbe questo ruolo: P.IVA, CF, SDI e PEC diventano colonne di prima classe.

### 2.3 Cutover

Acme resta in produzione durante lo sviluppo. **Non c'è importer Attio nello slice 1**: importare su un modello dati ancora in movimento significa farlo due volte. L'importer è previsto nello slice 2, a modello stabilizzato.

Il clone di riferimento sta in `.reference-acme/` (gitignored).

---

## 3. Decisioni di prodotto

| Decisione | Scelta | Motivazione |
|---|---|---|
| Tenancy | **Single-tenant self-hosted** | Un'istanza = un'azienda. Elimina isolamento tenant, row-level security, signup pubblico e billing. Multi-tenant eventualmente dopo, se il prodotto lo giustifica. |
| Auth umana | **Email + password, JWT in cookie httpOnly** | Zero dipendenze esterne, funziona in locale, test semplici. Utenti creati dall'admin. Google OAuth arriva allo slice 5 col Gmail sync, dove serve davvero il consenso Google. |
| Auth agenti | **Personal Access Token** generati dalla UI | L'MCP gira via stdio in locale: nessuna porta esposta, nessun OAuth da configurare. |
| Regime fiscale | **Configurabile, forfettario implementato** | `FiscalProfile` come dato di configurazione (regime, coefficiente ATECO, aliquota sostitutiva, INPS/cassa) con i valori attuali di Acme come default. Costo quasi nullo ora; l'ordinario si aggiunge senza toccare il modello dati. |
| Documentale | **Metadati in Postgres, byte su storage pluggable** | `LocalFileStorage` per sviluppo e self-hosting, `GDriveStorage` per la produzione attuale con le cartelle per cliente già esistenti. Ricerca, permessi e timeline funzionano identici. (Slice 2.) |

---

## 4. Architettura

### 4.1 Il principio

Un package Python `pigrocrm.core` contiene i servizi di dominio. **Non conosce né HTTP né MCP**: riceve Pydantic, restituisce Pydantic, possiede validazione e transazioni. Sopra ci stanno due adapter sottili — FastAPI e server MCP — che importano gli stessi servizi **in-process**.

```
     Web App (React)            Claude / client MCP
           │                            │
      FastAPI routers             MCP tools/resources
           └──────────┬─────────────────┘
                      │  (import diretto, in-process)
              packages/core — pigrocrm.core
        customers · people · deals · fields · auth
                      │
                 PostgreSQL
```

Nessuna chiamata di rete tra MCP e API. Aggiungere un tool MCP costa poche righe perché il lavoro è già fatto nel service.

**Alternative scartate.** *EAV per i campi custom*: ogni lettura diventa join+pivot, filtrare su due campi custom richiede due join, le performance degradano presto. *MCP come client HTTP dell'API*: paga latenza e serializzazione a ogni chiamata, il server MCP deve gestire auth/retry/errori HTTP, il debug attraversa due processi. Quest'ultima resta possibile in futuro come adapter aggiuntivo sopra gli stessi servizi, se servirà un MCP remoto.

### 4.2 La regola che tiene in piedi tutto

`packages/core` non importa **mai** da `apps/`. Un test automatico scandisce gli import e fallisce se trova `apps.`. Senza un controllo meccanico, "API-first" degrada nel giro di mesi — è esattamente ciò che è accaduto a Acme.

### 4.3 Struttura del monorepo

```
pigrocrm/
├── apps/
│   ├── api/                    # FastAPI — adapter HTTP sottile
│   │   ├── pigrocrm_api/
│   │   │   ├── routers/        # un router per dominio
│   │   │   ├── deps.py         # auth, sessione DB
│   │   │   ├── errors.py       # eccezioni dominio → RFC 9457
│   │   │   └── main.py
│   │   └── tests/
│   ├── mcp/                    # server MCP — adapter, importa core in-process
│   │   ├── pigrocrm_mcp/
│   │   │   ├── tools/          # rispecchia i domini
│   │   │   ├── resources/      # customer://, deal://, person://
│   │   │   └── server.py
│   │   └── tests/
│   └── web/                    # Vite + React + TS + TanStack Router + shadcn
│       ├── src/{routes,features,components/ui,lib}
│       └── tests/
├── packages/
│   └── core/                   # pigrocrm.core — il cuore
│       ├── pigrocrm/core/
│       │   ├── customers/      # models · schemas · repository · service
│       │   ├── people/
│       │   ├── deals/
│       │   ├── fields/         # + validator.py
│       │   ├── activities/
│       │   ├── auth/
│       │   ├── db/             # engine, sessione, migrazioni Alembic
│       │   └── errors.py
│       └── tests/
├── templates/                  # portati da Acme (slice 2+)
├── deploy/
├── docs/superpowers/specs/
├── docker-compose.yml
└── .github/workflows/
```

Ogni dominio è quattro file piccoli anziché uno grande: `models.py` (SQLAlchemy), `schemas.py` (Pydantic), `repository.py` (query), `service.py` (regole di business + transazioni). **Se `service.py` supera le ~300 righe, il dominio va diviso.**

---

## 5. Modello dati

Cinque tabelle di dominio e tre di supporto. Tutte con `id` (UUID v7), `created_at`, `updated_at` — tutti i timestamp sono `timestamptz` in UTC, con la conversione al fuso locale delegata al client. Tutti gli importi sono `numeric(12,2)`; le ore sono `numeric(8,2)`. Mai floating point per il denaro.

### 5.1 `customers`

I campi fiscali italiani sono **colonne di prima classe**: lo slice 3 ci costruisce sopra la FatturaPA, e Acme dimostra il costo dell'alternativa.

`ragione_sociale` (obbligatorio) · `partita_iva` · `codice_fiscale` · `codice_sdi` · `pec` · `indirizzo` · `cap` · `comune` · `provincia` · `nazione` (default `IT`) · `email` · `telefono` · `sito_web` · `stato` · `note` (Markdown) · `custom_fields` (JSONB) · `deleted_at`

### 5.2 `people`

`customer_id` **nullable**: un contatto può esistere prima di sapere per chi lavora, e forzare l'associazione produce clienti fantasma tipo "Freelance vari".

`nome` (obbligatorio) · `cognome` · `email` · `telefono` · `ruolo` · `linkedin` · `note` · `customer_id` (FK nullable) · `custom_fields` · `deleted_at`

### 5.3 `deals`

`customer_id` **obbligatorio**: un deal senza cliente non ha senso economico.

`nome` (obbligatorio) · `customer_id` (FK) · `pipeline_stage_id` (FK) · `valore_previsto` (numeric) · `probabilita` (int 0-100) · `data_chiusura_prevista` · `owner_id` (FK users) · `note` · `ore_preventivate` (numeric) · `valore_preventivato` (numeric) · `custom_fields` · `deleted_at`

`ore_preventivate` e `valore_preventivato` servono al preventivo-vs-consuntivo dello slice 4; aggiungerli ora costa zero.

### 5.4 `pipeline_stages`

`nome` · `posizione` (int) · `probabilita_default` (int) · `tipo` (`open` | `won` | `lost`)

Il `tipo` è necessario perché le dashboard devono sapere cosa significa "vinto" senza fare match sul nome. Seed: Lead → Contattato → Offerta → Negoziazione → Vinto (`won`) / Perso (`lost`). Configurabile da UI.

### 5.5 `users`

`email` (unique) · `password_hash` (argon2) · `nome` · `ruolo` (`admin` | `collaboratore` | `readonly`) · `attivo` (bool)

### 5.6 `field_definitions`

`entity_type` (`customer` | `person` | `deal`) · `key` (slug, unique per entity_type) · `label` · `field_type` · `options` (JSONB) · `required` (bool) · `position` (int) · `archived` (bool)

`entity_type` è un valore aperto: gli slice successivi vi aggiungono `document` e `invoice` senza modifiche allo schema né al validator.

Tipi supportati: `text`, `textarea`, `number`, `currency`, `date`, `select`, `multiselect`, `checkbox`, `url`.

Tre regole:

1. **Le definizioni si archiviano, non si cancellano.** Cancellare una definizione con valori ancora nel JSONB produce dati orfani invisibili. `archived=true` toglie il campo dall'interfaccia e lascia il dato leggibile.
2. **Cambiare `field_type` è vietato.** Da `text` a `number` con dati esistenti non esiste una risposta giusta. Si archivia il vecchio e si crea il nuovo. L'API risponde `409` con un messaggio che spiega il perché.
3. **La validazione vive in un solo posto**: `fields/validator.py`, chiamato dai service. Non nei router, non nei tool MCP, non nel frontend.

Indice `GIN` su ogni colonna `custom_fields`; le colonne native restano su B-tree.

### 5.7 `personal_access_tokens`

`user_id` (FK) · `nome` · `token_hash` · `prefix` (in chiaro, per riconoscerli in lista) · `last_used_at` · `revoked_at`

### 5.8 `activities` — la timeline

`entity_type` · `entity_id` · `kind` · `actor_id` · `actor_type` (`user` | `mcp` | `system`) · `payload` (JSONB) · `occurred_at`

Nello slice 1 registra creazioni, modifiche e cambi di stage. Negli slice successivi email, documenti, fatture e ore si aggiungono **senza migrazione**: è il punto di estensione che rende gratuita la timeline unificata.

`actor_type` non è cosmetico: in un CRM AI-first devi poter distinguere ciò che hai fatto tu da ciò che ha fatto Claude. È la prima cosa che vorrai sapere quando qualcosa va storto.

### 5.9 Cancellazioni

**Soft delete** (`deleted_at`) su `customers`, `people`, `deals`. La cancellazione accidentale via MCP è uno scenario realistico: un agente che interpreta male "elimina i deal chiusi" deve essere reversibile. Le query filtrano `deleted_at IS NULL` di default. **L'MCP non espone delete distruttivi nello slice 1**, solo archiviazione.

`DELETE /api/{entity}/{id}` **valorizza `deleted_at`, non rimuove la riga.** Nello slice 1 non esiste alcuna operazione di cancellazione fisica, né via API né via MCP: il ripristino avviene da database finché non ci sarà una UI dedicata. Cancellare un cliente **non** cancella a cascata persone e deal collegati; il servizio rifiuta con `Conflict` se esistono deal non archiviati, indicando quanti sono.

---

## 6. Service layer

### 6.1 Forma dei servizi

`CustomerService.create(data: CustomerCreate, actor: Actor) -> Customer`

Tre proprietà obbligatorie:

- **Riceve e restituisce Pydantic, mai oggetti HTTP.** Nessun `Request`, nessun `Response`, nessun codice di stato. Un service che sa cosa sia un 404 non è riusabile dall'MCP.
- **Riceve un `Actor` esplicito** — `{id, type: user|mcp|system, ruolo}` — non letto da variabile globale o contesto implicito. È ciò che rende l'autorizzazione testabile e la timeline onesta.
- **Possiede la transazione.** Un metodo di service = una unità atomica. `create_deal` scrive il deal e la sua activity, o nessuno dei due.

### 6.2 Errori

Eccezioni di dominio in `core/errors.py`: `NotFound`, `ValidationFailed`, `Conflict`, `PermissionDenied`, `ImmutableField`.

Portano **dati strutturati** (`entity`, `field`, `reason`), non stringhe formattate: la stessa eccezione deve diventare un problem detail HTTP *e* un messaggio comprensibile a un LLM, che sono due formattazioni diverse dello stesso fatto.

### 6.3 Autorizzazione

Applicata nel service layer, non nei router:

- `readonly` — sola lettura
- `collaboratore` — scrittura sulle entità, esclusa configurazione e gestione utenti
- `admin` — tutto

---

## 7. Adapter HTTP (FastAPI)

Deliberatamente noioso: valida il body, risolve l'`Actor` dal cookie JWT o dal PAT, chiama il service, serializza. Un `exception_handler` globale mappa le eccezioni di dominio su **RFC 9457** (`application/problem+json`).

**Un router che contiene un `if` di business logic è un bug**, e va trattato come tale in code review.

Endpoint dello slice 1:

```
POST   /api/auth/login · logout · refresh          GET /api/auth/me
CRUD   /api/customers · /api/people · /api/deals
PATCH  /api/deals/{id}/stage                       # spostamento Kanban
GET    /api/{entity}/{id}/timeline
CRUD   /api/field-definitions
CRUD   /api/pipeline-stages · /api/users · /api/tokens
GET    /api/schema/{entity_type}                   # schema corrente incl. campi custom
```

Lista con paginazione cursor-based, ordinamento e filtri (inclusi filtri su campi custom).

---

## 8. Adapter MCP

Altrettanto sottile, con due responsabilità aggiuntive.

### 8.1 Schema dinamico

Se l'utente ha aggiunto un campo custom "Settore", Claude non può indovinarlo. Quindi:

- I tool espongono lo **schema dinamico** costruito a runtime da `field_definitions`.
- Un tool `describe_schema` restituisce la forma corrente di ogni entità, letta dal database a ogni chiamata.

Senza questo, campi dinamici e MCP sono due funzionalità che si ignorano a vicenda.

**Meccanismo.** L'SDK MCP (`mcp` v2) inferisce lo schema di un tool dalla firma della funzione: `add_tool()` non accetta un JSON Schema esplicito. Il ponte è `pydantic.create_model()`, che costruisce a runtime il modello dell'entità a partire dalle `field_definitions`; il modello diventa l'annotazione del parametro del tool e l'inferenza produce lo schema corretto. **Lo stesso factory alimenta FastAPI**, quindi OpenAPI e MCP descrivono i campi custom dalla stessa fonte, senza duplicazione.

**Conseguenza da gestire.** Gli schemi dei tool sono fissati alla registrazione, e il processo MCP è distinto da quello dell'API: un campo aggiunto dalla web app non è visibile a un server MCP già avviato. Perciò `describe_schema` legge sempre dal vivo, e un tool `refresh_schema` ri-registra i tool dinamici ed emette `send_tool_list_changed()`.

### 8.2 Errori azionabili da un modello

`PermissionDenied` non diventa "403", diventa: *"Non puoi modificare i deal con ruolo readonly. Serve il ruolo collaboratore o admin."*

Un LLM che riceve un codice numerico ritenta a caso; uno che riceve una diagnosi si ferma o corregge.

### 8.3 Tool dello slice 1

```
describe_schema
create_customer · update_customer · get_customer · search_customers · archive_customer
create_person  · update_person  · get_person  · search_people  · archive_person
create_deal    · update_deal    · get_deal    · search_deals   · move_deal · archive_deal
list_pipeline_stages · get_timeline
```

### 8.4 Risorse

`customer://{id}` · `person://{id}` · `deal://{id}`

Restituiscono il contesto completo in Markdown — anagrafica, persone collegate, deal aperti, timeline recente — per far **leggere** prima di far **agire**.

### 8.5 Trasporto

**stdio** in locale, autenticato con un PAT generato dalla UI. Nessuna porta esposta, nessun OAuth da configurare.

---

## 9. Autenticazione

- Login → verifica argon2 → **JWT 15 minuti** in cookie `httpOnly` + `Secure` + `SameSite=Lax`
- **Refresh token 30 giorni**, ruotato a ogni uso
- **PAT**: `pgc_` + 32 byte random, salvati come **hash**, con `prefix` in chiaro per la lista, `last_used_at`, revoca. Mostrati una sola volta alla creazione.
- Nessun signup pubblico: gli utenti li crea l'admin
- **Bootstrap del primo admin**: comando CLI `pigrocrm createadmin` (`packages/core`), che legge email e password da argomenti o da prompt interattivo. Nessun account di default, nessuna password nota preconfigurata — la lezione diretta dalle credenziali hardcoded di Acme.

---

## 10. Frontend

### 10.1 Struttura

Layout in stile `shadcn-admin` (sidebar collassabile, header con breadcrumb e ricerca, area contenuto). Vite + TypeScript + TanStack Router file-based + shadcn/ui (TailwindCSS + RadixUI) + Lucide (Tabler solo per le icone brand) + ESLint/Prettier.

```
/login  ·  /  ·  /clienti  ·  /clienti/$id  ·  /persone  ·  /persone/$id
/deal (Kanban)  ·  /deal/lista  ·  /deal/$id
/impostazioni/{campi,pipeline,utenti,token}
```

### 10.2 Componenti trasversali

**`EntityDetailLayout`** — struttura di pagina identica per Cliente, Persona e Deal: *Panoramica · Timeline · Collegamenti*. Documenti, Attività e Fatture si aggiungono come tab negli slice successivi. È **un componente condiviso**, non tre pagine che si somigliano: tre pagine simili divergono, un componente no.

**`DynamicFieldRenderer`** — data una `field_definition`, produce il controllo giusto nei form e la cella giusta nelle tabelle. Scritto una volta, vale per tutte le entità e per ogni campo futuro senza toccare il frontend. È il moltiplicatore più alto dello slice.

**TanStack Query come unico strato dati.** Nessun `fetch` nei componenti. Client API **generato dallo schema OpenAPI**: un cambio di contratto rompe il type check, non la produzione.

**Kanban**: `dnd-kit` con aggiornamento ottimistico e rollback sull'errore.

### 10.3 Design system

Sono in gioco due sistemi visivi distinti e non direttamente compatibili:

- **Palette applicativa** — Watermelon `#ED254E`, Royal Gold `#F9DC5C`, Mint Cream `#F4FFFD`, Prussian Blue `#011936`, Charcoal Blue `#465362`. Satura, alto contrasto.
- **Sistema soft-aesthetic** (landing) — off-white `#FDFCF8`, Coral `#FFB7B2`, Sage `#E8EFE8`, Lavender `#EFEDF4`, grana, forme fluttuanti, `Outfit` + `Reenie Beanie`. Pastello, basso contrasto.

Applicare il secondo a una tabella di deal produce un'app illeggibile; applicare il primo a una landing wellness la rende aggressiva.

**Risoluzione:** Coral `#FFB7B2` è la tinta desaturata di Watermelon `#ED254E` — stessa famiglia cromatica, due livelli di energia.

- **App**: Prussian Blue come testo e superficie scura, Mint Cream come sfondo, Watermelon come azione primaria e stato critico, Royal Gold come attenzione, Charcoal Blue come testo secondario. Font `Outfit`. Contrasto **WCAG AA verificato**, dark mode inclusa.
- **Landing** (slice 5): espressione soft dello stesso sistema, con Watermelon **solo** sulle call-to-action — il visitatore vede calma, e l'unica cosa satura è il pulsante da premere.

Un unico file di token CSS, due mode. **Nello slice 1 si costruiscono solo i token e il tema dell'app.**

---

## 11. Testing

| Livello | Regola |
|---|---|
| **Unit sui service** | Il grosso della suite. **Postgres vero via testcontainers**, mai SQLite: JSONB e GIN non si simulano. |
| **Contract test API** | Verifica dello schema OpenAPI, così il frontend non scopre le rotture a runtime. |
| **Test MCP** | Invocazione reale dei tool contro DB di test. Un tool non testato si rompe in silenzio, perché nessun utente umano lo esercita. |
| **Test di architettura** | Scandisce gli import di `packages/core` e **fallisce** se trova `apps.`. Tre righe, protegge l'unica decisione non recuperabile. |
| **E2E Playwright** | Solo i percorsi critici: login, crea cliente, crea deal, sposta nel Kanban. |

**TDD** per la logica di dominio: service e `fields/validator.py` si scrivono test-first — è la parte con regole vere, dove i test ripagano subito.

---

## 12. Deploy

Riuso della pipeline di Acme, con i test come gate aggiuntivo:

1. **CI**: lint + type check + test (Python e frontend) + build
2. **Sync**: `rsync` con esclusioni esplicite di `.env` e artefatti
3. **Deploy**: `docker compose up -d --build` via SSH, con fallback `docker compose` / `docker-compose`
4. **Nginx**: configurazione idempotente via script

`docker-compose.yml`: servizio `api` (FastAPI + uvicorn), `web` (build statica servita da nginx), `db` (PostgreSQL con volume persistente). Migrazioni Alembic eseguite all'avvio dell'API.

---

## 13. Criteri di successo dello slice 1

1. Un utente fa login, crea un cliente con un campo custom definito da UI, ci associa una persona e un deal, e sposta il deal nel Kanban.
2. **Claude esegue le stesse operazioni via MCP**, scoprendo il campo custom tramite `describe_schema` senza che sia stato codificato da nessuna parte.
3. La timeline dell'entità mostra entrambe le sequenze, distinguendo `actor_type` `user` da `mcp`.
4. Il test di architettura passa: `packages/core` non importa da `apps/`.
5. La suite gira in CI su Postgres reale e il deploy va a buon fine su server.

---

## 14. Fuori ambito (slice successivi)

| Slice | Contenuto |
|---|---|
| **2** | Documenti e template: storage pluggable (local/GDrive), motore `{{}}` con loop e condizionali, render PDF Pandoc+Typst, versioning, tipo documento, stati offerta, **importer Attio** |
| **3** | Fatturazione: fatture multi-riga, numerazione progressiva, `FiscalProfile`, FatturaPA FPR12, fatture temporanee |
| **4** | Time tracking, costi, P&L, preventivo vs consuntivo, calcolo fiscale nel service layer |
| **5** | Gmail (OAuth, sync conversazioni rilevanti, invio, solleciti) + landing page e design system soft-aesthetic |
| **6** | Dashboard commerciale/economica/operativa, ricerca globale, automazioni, prompt MCP contestuali |

### Semplificazione adottata dal documento originale

L'**Offerta cessa di essere un'entità separata a livello di interfaccia**. Esiste un *Documento del Deal* con un tipo (Offerta, Contratto, Verbale, Documento); se il tipo è Offerta ottiene versioning, stati (Bozza/Inviata/Accettata/Rifiutata) e conversione PDF. Meno concetti da imparare, stessa flessibilità. (Slice 2.)
