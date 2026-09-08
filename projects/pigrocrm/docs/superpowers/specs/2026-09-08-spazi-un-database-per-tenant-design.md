# Spazi — un CRM per iscritto, un database per spazio

**Data:** 2026-09-08
**Ambito:** dal login di https://pigro.joinorbiters.com chiunque può creare il proprio spazio con
nome, email e password. Lo spazio risponde a `https://pigro.joinorbiters.com/<nome>` ed è un
PigroCRM completo e isolato. I nomi sono unici e alcuni sono riservati.

---

## 1. La scelta: un database per spazio, non una colonna per riga

PigroCRM è single-tenant per costruzione, e lo resta: nessun servizio, nessuna tabella e nessuna
query imparano cosa sia un tenant. Ogni spazio è **un database Postgres a sé**, con lo stesso schema
migrato da Alembic, i suoi utenti, il suo registro fatture senza buchi, le sue chiusure di periodo.
L'unica cosa che cambia è quale database l'API apre per una richiesta, e lo decide il primo
segmento dell'URL.

L'alternativa, una colonna `tenant_id` su trenta tabelle e in ogni query, avrebbe toccato tutto il
prodotto per lo stesso risultato e reso ogni dimenticanza una fuga di dati fra clienti. Qui una
dimenticanza è impossibile: la richiesta ha una sola connessione, a un solo database.

L'installazione di Ivan resta la **radice**: `https://pigro.joinorbiters.com/app` e `/api` senza
prefisso usano `PIGROCRM_DATABASE_URL` come prima.

## 2. Il registro

Un database di servizio, `pigrocrm_tenants` (stesso server e credenziali di `PIGROCRM_DATABASE_URL`,
o `PIGROCRM_TENANTS_DATABASE_URL`), creato al primo uso come `orbiters`. Una tabella `tenants`:
`slug` (unico), `db_name`, `owner_email`, `created_at`. L'unicità è un indice del database, non un
controllo dell'applicazione: due iscrizioni con lo stesso nome nello stesso istante ne vedono
passare una sola.

## 3. Il nome

Minuscolo, da 3 a 32 caratteri, lettere, cifre e trattini, non inizia né finisce con un trattino.
Dal nome che la persona scrive si ricava lo slug (accenti tolti, spazi in trattini) e la pagina lo
mostra come URL prima dell'invio. Riservati, perché sono già percorsi del sito: `app`, `api`,
`health`, `assets`, `privacy`, `termini`, `orbiters`, `pigrocrm`, `login`, `www`, `admin`, `static`.

## 4. Il provisioning

`POST /api/tenants` con `slug`, `nome`, `email`, `password`. In ordine: riga nel registro (qui
cade il duplicato, 409), `CREATE DATABASE`, `alembic upgrade head` sul nuovo database con la
stessa `env.py` di produzione, poi il primo utente admin con `UserService.create` (stessa
validazione della password, stessa timeline). Se un passo dopo la riga fallisce, il database viene
eliminato e la riga tolta: non restano spazi a metà. Risposta 201 con lo slug e l'URL di login.
`GET /api/tenants/{slug}/disponibile` dice alla pagina se il nome è libero mentre la persona scrive.

## 5. La richiesta

Un middleware ASGI riconosce `^/<slug>/(api|health)` e, se lo slug non è riservato, toglie il
prefisso dal percorso e annota lo slug sulla richiesta. `get_session` apre il database dello spazio
(un engine per spazio per processo, come oggi per la radice); uno slug sconosciuto è 404 «spazio
non trovato». I cookie di sessione hanno `path=/<slug>/`, così due spazi nello stesso browser non
si parlano.

Per gli spazi Gmail e Drive **non esistono**: le impostazioni che la richiesta vede hanno il client
Google vuoto, quindi l'interfaccia nasconde le sezioni e gli endpoint rispondono 409, come su
un'installazione che non ha Google. I documenti vanno su disco, in `var/documents/tenants/<slug>`.
Il callback OAuth è uno per installazione e tornerebbe alla radice: collegare Google a uno spazio è
lavoro futuro, non un caso gestito male.

## 6. La SPA e nginx

Il bundle è uno. `nginx` serve `/<slug>/app/*` con lo stesso `index.html` della radice e inoltra
`/<slug>/api/*` all'API con il percorso intero. La SPA legge il prefisso dall'URL: `basepath` del
router e `baseUrl` del client API valgono `/<slug>` quando c'è. `/<slug>` da solo rimanda a
`/<slug>/app/`.

Il login della radice ha un secondo bottone, «Crea il tuo spazio», che apre `/app/registrati`.
Sotto uno spazio quel bottone non c'è: ci si iscrive solo dalla radice.

## 7. Verifica

- `packages/core/tests/test_tenants.py`: slug, riservati, provisioning reale (database, `alembic_version`
  alla testa, un admin), duplicato, ripulitura dopo un fallimento.
- `apps/api/tests/test_tenants_api.py`: 201, 409, 422, disponibilità, login sotto `/<slug>/api` con
  cookie scopato, dati dello spazio separati dalla radice, slug sconosciuto 404, Gmail assente.
- `apps/web/src/routes/app/registrati.test.tsx`: slug derivato dal nome, URL mostrato, errori.
- `apps/web/src/lib/tenant.test.ts`: il prefisso letto dall'URL.
