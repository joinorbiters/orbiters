# PigroCRM

> Il CRM che lavora al posto tuo.

CRM **AI-first** per freelancer, consulenti e piccole startup italiane. Ogni operazione disponibile
nell'interfaccia web è accessibile anche via REST API e via **MCP** (Model Context Protocol),
così un agente come Claude può fare tutto ciò che fai tu.

Copre l'intero ciclo senza cambiare applicazione:

```
Contatto → Cliente → Deal → Offerta → Lavoro → Time Tracking → Fattura → Analisi economica
```

## Principi

- **Lean by default** — ogni funzionalità è usabile senza configurazione; le personalizzazioni sono opzionali.
- **API first** — la UI usa esclusivamente le API pubbliche. Nessuna logica esiste solo nel frontend.
- **MCP first** — il server MCP non è un adattatore aggiunto dopo: usa gli stessi servizi della UI, in-process.
- **Nessuna duplicazione** — ogni dato è salvato una volta sola.
- **Single-tenant dentro, più spazi fuori** — nessun servizio conosce i tenant. Chi si iscrive
  dal login ottiene uno *spazio*, cioè un database Postgres a sé con lo stesso schema, servito
  su `/<nome>/app` e `/<nome>/api`; l'installazione radice resta com'è. Vedi
  `docs/superpowers/specs/2026-09-08-spazi-un-database-per-tenant-design.md`.

## Stack

| | |
|---|---|
| Backend | Python · FastAPI · SQLAlchemy · Alembic |
| Database | PostgreSQL |
| Frontend | Vite · React · TypeScript · TanStack Router · shadcn/ui (Tailwind + Radix) |
| Documenti | Pandoc + Typst |
| Deploy | Docker Compose · nginx · GitHub Actions |

## Deploy

Un primo deploy fatto fuori ordine produce uno stack che si avvia ma in cui **nessuno riesce ad
accedere**, senza un solo errore in un log a spiegare perché. I passaggi sotto vanno seguiti in
quest'ordine.

### Prerequisiti sul server

- Docker Engine, il plugin Docker Compose e `certbot` (con il plugin nginx) installati.
- Un record DNS che punti il dominio scelto a questo server.
- L'utente che esegue il deploy deve appartenere al gruppo `docker` **e** deve essere `root` (o
  avere sudo equivalente): `deploy/setup-server.sh` scrive in `/etc/nginx/sites-available/`,
  crea il symlink in `sites-enabled/`, esegue `nginx -t` e `systemctl reload nginx`, tutte
  operazioni che richiedono privilegi di root. `ci-deploy.yml` lancia questo stesso script via
  SSH assumendo che l'utente configurato in `PIGROCRM_USER` lo sia già; questo repository non
  prova a bypassare il requisito con `sudo` non interattivo, perché funzionerebbe solo assumendo
  che ogni server di destinazione abbia già una regola sudoers passwordless preconfigurata per
  esattamente questi comandi — una premessa non verificabile da qui, ed equivalente al requisito
  di sopra sotto un altro nome.
- **`pg_trgm`.** Le migrazioni eseguono `CREATE EXTENSION IF NOT EXISTS pg_trgm`
  all'avvio dell'API. Sull'immagine `postgres:17-alpine` del compose l'utente
  `pigrocrm` è superuser e funziona senza intervento. Su un PostgreSQL gestito serve
  che il fornitore abbia `pg_trgm` in allowlist e che l'utente possa creare estensioni:
  senza, **il deploy fallisce all'avvio** — che è il comportamento voluto, perché
  l'alternativa è un'applicazione che parte e scansiona sequenzialmente in silenzio.
  Sintomo esatto nei log: `permission denied to create extension "pg_trgm"`.

### 1. `.env`

Copia `.env.example` nella radice del repository **sul server** (non solo in locale) come
`.env` e compila:

- `POSTGRES_PASSWORD` — obbligatoria: `docker compose` si rifiuta di partire senza.
- `PIGROCRM_JWT_SECRET` — genera un segreto vero (`openssl rand -hex 32`), diverso da
  qualunque valore usato in sviluppo locale.
- Lascia `PIGROCRM_COOKIE_SECURE` come sta: `docker-compose.yml` non la inoltra mai al
  container `api`, di proposito (vedi il commento lì) — riguarda solo il flusso di sviluppo
  locale più sopra nello stesso file.

### 2. Avvia lo stack

```
cd projects/pigrocrm
docker compose --env-file ../../.env up -d --build
```

Il file compose sta nella cartella del progetto, ma il `.env` resta nella radice del
repository (passo 1): senza `--env-file` compose lo cercherebbe accanto a sé, non
troverebbe `POSTGRES_PASSWORD` e si rifiuterebbe di partire.

Porta su `db` (Postgres), `api` (migra da solo all'avvio) e `web` (nginx con la SPA compilata,
in ascolto solo su `127.0.0.1:8080` — non ancora raggiungibile da internet).

### 3. Configura nginx sull'host

```
sudo bash deploy/setup-server.sh
```

Scrive un vhost che fa da reverse proxy verso `127.0.0.1:8080`, per ora solo in HTTP. Usa il
dominio di default (`pigrocrm.humancraft.tech`) a meno di impostare `PIGROCRM_DOMAIN`:
`sudo PIGROCRM_DOMAIN=tuodominio.it bash deploy/setup-server.sh`. Idempotente: rilanciarlo ad
ogni deploy successivo, come fa `ci-deploy.yml`, non tocca la configurazione TLS che il passo
seguente aggiunge.

### 4. Attiva TLS — prima di provare ad accedere

```
sudo certbot --nginx -d tuodominio.it
```

(lo stesso dominio del passo precedente). Passo manuale e una tantum, non automatizzato da CI.

**Nessun login funziona prima di questo passo, e senza un solo errore visibile.**
`cookie_secure` (`packages/core/src/pigrocrm/core/config.py`) vale `true` di default e
`docker-compose.yml` non lo sovrascrive mai per il container `api`, di proposito — è la stessa
protezione che impedisce a chi intercetta una rete non cifrata di rigiocare il cookie di
sessione. Su semplice HTTP il browser scarta silenziosamente un cookie `Secure`: il login
risponde comunque 200, ma ogni richiesta successiva risulta non autenticata (lo stesso
meccanismo che `.env.example` descrive per Safari in sviluppo locale — qui capita di default,
in produzione, sul primo deploy, in ogni browser).

### 5. Crea il primo amministratore

Non esiste nessun utente né password di default (la lezione diretta delle credenziali
hardcoded di the previous system):

```
# I dati di Postgres stanno sull'host in PIGROCRM_DATA_DIR (vedi .env.example): un reset di
# Docker non li tocca. Backup: `scripts/backup-db.sh` (pg_dumpall datato, ultimi 30 tenuti).
docker compose exec api uv run --no-sync pigrocrm createadmin --email admin@tuodominio.it --nome "Nome Cognome"
```

Chiede la password a terminale, due volte (mai come argomento o variabile d'ambiente).
`--no-sync` non è decorativo: senza, `uv run` dentro il container risincronizza l'ambiente
contro l'intero `pyproject.toml`, gruppo `dev` incluso (mypy, ruff, pytest, ...), scaricandoli
dalla rete dentro un container di produzione già in esecuzione ad ogni singola invocazione
(vedi il commento in `Dockerfile.api`).

### 6. Accedi

`https://tuodominio.it/`, con le credenziali appena create.

## Stato

In sviluppo. Sostituirà [the previous system](https://example.com).

Le specifiche sono in [`docs/superpowers/specs/`](docs/superpowers/specs/).
