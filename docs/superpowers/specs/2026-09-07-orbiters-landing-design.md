# Orbiters — landing di iscrizione alla community

**Data:** 2026-09-07
**Ambito:** una sola pagina, `/orbiters`, che presenta Orbiters (la community di freelance di
PigroCRM: lavoro trovato insieme, strumenti per fatturare e farsi pagare) e raccoglie un
indirizzo email. Niente altro: nessuna area riservata, nessuna newsletter inviata, nessuna
analitica.

---

## 1. Cosa si costruisce

Una pagina statica nel build della landing (`apps/web/landing/`), servita da nginx alla radice
come `/privacy` e `/termini`. Un endpoint pubblico, `POST /api/orbiters/signups`, che salva
l'email in un **database Postgres dedicato**, separato da quello del CRM.

## 2. Perché un database separato

La lista di chi vuole entrare in Orbiters non è un dato del CRM. Non è di un cliente, non entra
in nessuna fattura, non ha un titolare che la tratta per conto proprio. Tenerla nello stesso
schema del CRM la farebbe finire in ogni dump, in ogni backup e in ogni migrazione del prodotto
self-hosted, cioè in mano a chiunque installi PigroCRM per sé. Va invece nel database
`orbiters`, sullo stesso server Postgres, con la sua tabella e nulla altro.

Per lo stesso motivo il database non passa per Alembic: le migrazioni di `packages/core`
descrivono lo schema del CRM e ogni installazione le esegue. Il database `orbiters` viene creato
dall'API al primo uso, in modo idempotente (`CREATE DATABASE` se manca, `create_all` della sua
unica tabella), e un'installazione che non riceve mai un'iscrizione non lo vede mai.

L'URL è derivato da `PIGROCRM_DATABASE_URL` cambiando solo il nome del database, oppure
esplicito in `PIGROCRM_ORBITERS_DATABASE_URL`. La creazione richiede che l'utente Postgres possa
fare `CREATE DATABASE`: nell'immagine `postgres:17-alpine` del compose è superuser, come già
per `pg_trgm`.

## 3. Il dato

Tabella `signups`: `id` (uuid7), `email` (String 320, unica su `lower(email)`), `created_at`.
L'email è normalizzata in minuscolo prima di essere salvata. Una seconda iscrizione con lo stesso
indirizzo non è un errore: la pagina risponde "sei in orbita" in entrambi i casi, e l'API
distingue con lo status (201 la prima volta, 200 le successive) e con il campo `nuova`.

## 4. La pagina

Stile preso da craft.wild.as: pagina chiara con una griglia appena visibile, e un campo di
tessere quadrate colorate. Le tessere sono dipinte su un `<canvas>` da uno script di circa due
kilobyte che legge i colori dalle custom property CSS, così la palette resta quella condivisa
con l'app (`palette-plugin.ts`) e lo script non ne contiene una copia. Senza JavaScript la
pagina mostra la griglia e il box; il campo di tessere semplicemente non c'è.

Comunicazione presa da Acme: seconda persona, imperativi, una sola idea per frase. Un box
centrale con il nome, una frase, un campo email e un bottone. Nessun link a terzi, nessun
analytics, la stessa woff2 dell'app.

Il box ha bordi netti e un'ombra a gradino: l'estetica a pixel non è compatibile con i raggi e
le ombre morbide di `landing.css`, quindi la pagina ha il suo foglio di stile e non lo importa.

## 5. Verifica

- `packages/core/tests/test_orbiters.py`: creazione idempotente del database, normalizzazione,
  seconda iscrizione, indirizzo non valido.
- `apps/api/tests/test_orbiters_api.py`: l'endpoint senza autenticazione, 201 poi 200, 422 su
  indirizzo non valido.
- `apps/web/landing/orbiters.test.ts`: meta, lingua, un solo form, nessuna risorsa esterna,
  budget dello script.
- `apps/web/e2e/landing-served.spec.ts`: `/orbiters` risponde 200 dallo stack compose.

## 6. Dove gira

Dal 7 settembre 2026 la pagina risponde su **https://joinorbiters.com**, su un server Hetzner
dedicato (Ubuntu, Docker). Lo stack è quello di `docker-compose.yml`, clonato in
`/opt/pigrocrm` con una deploy key in sola lettura e ascoltato solo su `127.0.0.1:8080`; sopra
c'è nginx dell'host con il vhost `deploy/nginx/joinorbiters.conf` (più lo snippet
`orbiters-proxy.conf` in `/etc/nginx/snippets/`), che espone la sola pagina, i suoi asset, le due
pagine di policy e l'endpoint delle iscrizioni. `/app/` e il resto dell'API non sono
raggiungibili da quel nome. TLS via `certbot --nginx`, che riscrive il vhost sul posto.

Aggiornare: `ssh orbiters 'cd /opt/pigrocrm && git pull --ff-only && docker compose up -d --build'`.
Leggere la lista: `docker compose exec db psql -U pigrocrm -d orbiters -c "select email, created_at from signups"`.
