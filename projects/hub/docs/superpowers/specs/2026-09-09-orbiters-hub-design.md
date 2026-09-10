# Orbiters Hub: a product of its own, with the signup wizards, the company flow and the admin area

Date: 2026-09-09. Status: analysis, approved in conversation by Ivan the same day, not
yet implemented. Tracker: the Website project in Linear for now (Ivan's choice; a Hub
project per `docs/adding-a-project.md` §9 once the code exists).

## What Ivan asked for, and the decisions taken with him

- An **admin hub** in the PigroCRM visual style that becomes the main hub of Orbiters.
- **Registration as a guided wizard**, Typeform/Tally style: nome, cognome, email,
  LinkedIn (optional), CV upload, daily rate, position, remote availability, additional
  links.
- A **dedicated flow for companies**: company name, a short project description, the
  period of need, the daily budget.
- The joinorbiters.com landing sends people to the hub when they want to sign up.
- A **new landing** that tells the project better -- CTAs, perks, clients and
  testimonials -- with example.com as the structural reference. For now it
  **replaces `/pigrocrm`**; the root `/` stays as it is today.
- **Decoupled from PigroCRM**: Orbiters is a distinct product on the database, the API
  and the MCP side. Nothing of it stays inside `pigrocrm-core`, `pigrocrm-api` or
  `pigrocrm-mcp`.
- The admin area is a **dedicated section of the hub**, with its own login -- not a
  section of PigroCRM.
- The hub answers at **joinorbiters.com/hub/**.
- Clients and testimonials are **placeholders** in one combined section shaped as
  "Mario Rossi ha lavorato per XYZ" plus a quote, until Ivan supplies the real ones.
- **CVs live in the Orbiters database.**

## Today: what is Orbiters-shaped inside PigroCRM

Everything below moves. The list is the inventory of `grep -rli orbiters projects/pigrocrm`
minus the three things that legitimately stay (see the end of this section).

| Where | What | Lines |
| --- | --- | --- |
| `packages/core/src/pigrocrm/core/orbiters/` | `models.py` (Signup, LATE_COLUMNS), `schemas.py`, `service.py`, `database.py` (`ensure_orbiters_database`, the one-table "migration" by `ADD COLUMN IF NOT EXISTS`), `conversions.py` (ChatGPT Ads Conversions API), `__init__.py` | 684 |
| `apps/api/src/pigrocrm_api/routers/orbiters.py` | `POST /api/orbiters/signups`, token-bucket rate limit, UTM capture, server-side conversion | 205 |
| `apps/api/src/pigrocrm_api/deps.py`, `main.py` | the orbiters engine dependency and the router include | -- |
| `apps/mcp/src/pigrocrm_mcp/tools/orbiters.py`, `server.py` | `list_orbiters_signups` | -- |
| `packages/core/src/pigrocrm/core/cli.py` | `pigrocrm conversions-check` | ~60 |
| `packages/core/src/pigrocrm/core/config.py` | `orbiters_database_url`, `openai_pixel_id`, `openai_conversions_api_key`, `orbiters_signup_url`, `openai_conversions_send_hashed_email` | -- |
| `docker-compose.yml`, `.env.example`, `README.md`, `AGENTS.md` | the five variables above and their prose | -- |
| tests | `core/tests/test_orbiters.py`, `test_orbiters_conversions.py`, `test_compose_environment.py` (the variables), `api/tests/test_orbiters_api.py`, `mcp/tests/test_orbiters_tool.py`, `test_mcp_surface_coverage.py` (the tool count) | -- |
| `deploy/nginx/pigro.joinorbiters.conf`, `spa.conf` | comments only | -- |

Stays in PigroCRM: `db/sidecar.py` (also used by `tenants/` and `storage/local.py`),
the reserved slug `orbiters` in `tenants/schemas.py` (a URL namespace rule of the CRM,
not Orbiters code), and the historical specs under `projects/pigrocrm/docs/`.

The `orbiters` **database already exists** on the production Postgres, beside
`pigrocrm`, with the `signups` table and Ivan's real waitlist in it. Distinct database,
same server. The website's form posts to `/api/orbiters/signups`, which the host nginx
proxies to the PigroCRM API container.

## The product: `projects/hub`

The PigroCRM layout, because it is the layout this repository knows how to lint, test,
build and deploy:

```
projects/hub/
  packages/core/   orbiters_core: models, Alembic migrations, services, conversions
  apps/api/        orbiters_api: FastAPI, its own Postgres, cookie sessions for admins
  apps/mcp/        orbiters_mcp: stdio, the same services in process
  apps/web/        the hub SPA (React + Vite), served at /hub/
  deploy/          compose (db, api, web) on 127.0.0.1:8084, the nginx locations
  docs/            this spec and the ones after it
```

`packages/core` imports neither adapter, enforced as in PigroCRM. Distribution names
`orbiters-core`, `orbiters-api`, `orbiters-mcp`; environment prefix `ORBITERS_`.

### Database (`orbiters`, Alembic of its own)

- `signups` -- as today, taken over: same columns, existing rows kept. Migration 0001
  is written against the table as it exists in production (`CREATE TABLE IF NOT
  EXISTS` plus the late columns), so the first `alembic upgrade head` adopts it rather
  than recreating it.
- `freelancers` -- id, nome, cognome, email, linkedin_url, `cv_bytes` (bytea, 5 MB
  cap), `cv_filename`, `cv_mime`, `cv_size`, `tariffa_giornaliera` (numeric 10,2),
  `posizione` (text), `remoto` (`remoto` | `ibrido` | `in_sede`), `links` (jsonb list
  of URLs), the six UTM columns, `stato` (`nuovo` | `contattato` | `attivo` |
  `scartato`), `note`, `created_at`, `updated_at`.
- `companies` -- id, nome_azienda, referente, email, progetto (text), `periodo_da`
  (date), `durata` (text, free: "3 mesi", "fino a dicembre"), `budget_giornaliero`
  (numeric 10,2), the six UTM columns, `stato` (`nuovo` | `contattato` | `in_corso` |
  `chiuso`), `note`, `created_at`, `updated_at`.
- `admin_users` -- id, email, password_hash, nome, created_at; `admin_sessions` for the
  refresh token. A minimal copy of PigroCRM's session design (httpOnly access cookie
  15 min, rotating refresh cookie), not a shared library: the two products must be able
  to change it independently, and it is two hundred lines.

### API (`orbiters_api`)

Public, rate-limited like the signup is today, UTM captured from the body:

- `POST /api/orbiters/signups` -- moved as is, same path, so the website's form and the
  ChatGPT Ads conversion keep working unchanged.
- `POST /api/hub/freelancers` -- multipart: the fields plus the CV file (PDF, 5 MB).
- `POST /api/hub/companies` -- JSON.

Admin (cookie session):

- `POST /api/hub/auth/login`, `/logout`, `/refresh`, `GET /api/hub/auth/me`.
- `GET /api/hub/freelancers` (filters: stato, search; cursor), `GET .../{id}`,
  `GET .../{id}/cv` (the bytes, `Content-Disposition` from `cv_filename`),
  `PATCH .../{id}` (stato, note).
- The same three for `/api/hub/companies`; `GET /api/hub/signups`.
- `GET /health` reading the database.

First admin: `orbiters createadmin` on the server, as PigroCRM does.

### MCP (`orbiters_mcp`)

A personal access token is out of scope for the first cut; the server authenticates
with an admin email and password from its environment, like a cron would. Tools:
`list_signups`, `list_freelancers`, `get_freelancer`, `list_companies`, `get_company`,
`set_freelancer_status`, `set_company_status`, `add_note`. Read mostly; no deletion.

### Web (`apps/web`, at `/hub/`)

PigroCRM's look: `shared/brand` palette and typeface, the same radii, borders and
shadows as `tokens.css`, the same header/panel shapes. Not PigroCRM's component library
imported across projects -- the hub copies the six primitives it needs (button, input,
select, checkbox, card, progress) so the two products can diverge.

- `/hub/` -- the chooser: «Sono un freelance» / «Cerco persone per un progetto».
- `/hub/freelance` -- the wizard, one question per screen, a progress bar, Enter to
  continue, Back always available, the CV step with drag-and-drop, a review screen,
  then `/hub/grazie`.
- `/hub/aziende` -- the company wizard, same mechanics, five steps.
- `/hub/admin/login`, `/hub/admin/freelance`, `/hub/admin/freelance/:id`,
  `/hub/admin/aziende`, `/hub/admin/aziende/:id`, `/hub/admin/iscrizioni` -- the
  lists in the CRM's table shape (status pills, row actions), the detail with the CV
  download and the status/notes editor.

### Landing (`projects/website`)

`src/index.html` is rewritten as the Orbiters landing and keeps being served at
`/pigrocrm` (Ivan's instruction for now; the root stays `orbiters.html`). Structure,
from example.com: hero with the claim and two CTAs («Entra come freelance» →
`/hub/freelance`, «Cerchi persone? Raccontaci il progetto» → `/hub/aziende`); «Come
funziona» in three steps; the perks list (PigroCRM gratis, progetti da aziende vere,
persone con cui parlarne, strumenti per fatturare e farsi pagare); one combined
section «Hanno lavorato con noi» with four placeholder tiles shaped «Mario Rossi ha
lavorato per XYZ» each carrying a quote, an initial and a role, marked as placeholders
in the markup until the real ones arrive; the PigroCRM perk box; footer. The email
form on `/` keeps posting to `/api/orbiters/signups` and gains a line pointing at the
hub.

### Deploy

- `projects/hub/docker-compose.yml`: `db` (its own Postgres, data under the host
  directory `ORBITERS_DATA_DIR` names, outside the repository), `api`, `web` on
  `127.0.0.1:8084`.
- Host nginx `joinorbiters.conf`: `location ^~ /hub/` → 8084; `location ^~ /api/hub/`
  and `location = /api/orbiters/signups` → the hub API (the latter re-pointed from the
  PigroCRM API). Nothing on pigro.joinorbiters.com changes.
- Data: `pg_dump orbiters` from the PigroCRM Postgres, restore into the hub's Postgres,
  then run the hub migrations; the PigroCRM copy is dropped only after a week of the
  hub answering.
- Workspace wiring: `pyproject.toml` members and `[tool.mypy] files`, `ruff.toml` per
  project, `pnpm-workspace.yaml` already globs `projects/*/apps/*`, `ci.yml` filters
  `hub_py`/`hub_web`, `preflight.json` checks, `deploy-hub.yml` caller, GitHub
  environments `hub-preview`/`hub-production`.

## Work plan

1. **Extraction** -- `projects/hub/packages/core` with the code moved from PigroCRM
   (signups, conversions), Alembic adopting the existing table, `orbiters_api` with the
   moved signup route and health, `orbiters_mcp` with `list_signups`. PigroCRM loses the
   module, the router, the tool, the CLI command, the five settings and their tests;
   its compose stops forwarding them. Both products green.
2. **Freelancers and companies** -- tables, services, public multipart/JSON routes,
   MCP reads, tests.
3. **Admin auth and admin API** -- users, sessions, `createadmin`, the admin routes.
4. **Hub web** -- primitives, the chooser, the two wizards, the thank-you page, the
   admin section.
5. **Landing** -- the new `index.html` and its tests; the pointer on `/`.
6. **Deploy** -- compose, nginx, data move, deploy workflow; Linear Hub project.

Each step ships on its own, verified, and is a separate deploy.

## Open points

- Privacy: the CV is personal data. `/privacy` gets a paragraph on what is kept, for
  how long and how to ask for deletion; the wizard links it before the CV step.
- CV retention: not decided; proposed 24 months from the last contact.
- Whether `list_orbiters_signups` disappears from the PigroCRM MCP the day the hub
  MCP exists, or a week later (Ivan's Claude sessions use it today).
