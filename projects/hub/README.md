# Orbiters hub

Orbiters, the freelance community, as a product of its own: the signup form the
community site collects, the freelancer and company wizards, and the admin area that
reads them. Served at `joinorbiters.com/hub/`. Split out of PigroCRM on 2026-09-09 so
the two products change independently — its own settings (`ORBITERS_*`), its own
Postgres, its own Alembic history, its own API and MCP server. Nothing here imports
PigroCRM, and PigroCRM imports nothing from here.

The design record is
[`docs/superpowers/specs/2026-09-09-orbiters-hub-design.md`](docs/superpowers/specs/2026-09-09-orbiters-hub-design.md).
Read it before changing the shape of anything here; this file does not restate it.

## What it does

Three public flows and the admin area behind them:

- `/hub/` — the chooser: «Sono un freelance» / «Cerco persone per un progetto».
- `/hub/freelance` — the freelancer wizard (CV upload included), ending at `/hub/grazie`.
- `/hub/aziende` — the company wizard.
- `/hub/accedi` and `/hub/io`: a freelancer gets back in with a magic link by mail, to
  see or change what they sent.
- `/hub/admin/login` and the freelancer, company and signup lists behind it — a cookie
  session. The first admin is created with `orbiters createadmin` (below); the next ones
  from «Amministratori» inside the area.

`POST /api/orbiters/signups` is the community site's signup endpoint, moved here
unchanged on 2026-09-09: the website's form and the ChatGPT Ads conversion still post
to the same path.

## Layout

```
packages/core/   orbiters_core: models, Alembic migrations, services, the ad conversion
apps/api/        orbiters_api: FastAPI, one process, its own database
apps/mcp/        orbiters_mcp: stdio, the same services in process
apps/web/        pnpm package `hub`: the SPA at joinorbiters.com/hub/
```

`packages/core` imports neither adapter, and neither adapter imports the other.

## Running it

Python, from the repository root:

```
uv sync --frozen
uv run pytest -q projects/hub/packages/core/tests projects/hub/apps/api/tests projects/hub/apps/mcp/tests
uv run --env-file projects/hub/.env uvicorn orbiters_api.main:app --port 8010
```

The tests bring a `testcontainers` Postgres to `head` with this package's migrations,
never with `create_all`.

Web, also from the root:

```
pnpm --filter hub dev      # :5180, with /api proxied to a running hub API on :8084
pnpm --filter hub build
pnpm --filter hub test
pnpm --filter hub lint
```

The full stack, its own Postgres included, from this directory:

```
cd projects/hub
docker compose -p orbiters up -d --build
```

`-p orbiters` is not decorative: without it compose names the stack after the
directory, and a second stack starts beside the one already running rather than
joining it.

## Ports and the environment file

Loopback only, production values (`docs/adding-a-project.md` §7 has preview's):

| Service | Port |
|---|---|
| api | 8084 |
| web | 8085 |
| Postgres | 55435 |

`.env.example` lists every variable the compose file needs: `POSTGRES_*`,
`ORBITERS_DATABASE_URL`, the ports above, the ChatGPT Ads pair, and
`ORBITERS_DATA_DIR` — Postgres' data directory, outside the repository, with no
default in `docker-compose.yml`, so a `.env` that forgets it fails the stack rather
than mounting an empty one. The `.env` itself is never in the repository. Locally it
is `projects/hub/.env`, beside the compose file. On a server it is
`${DEPLOY_PATH}/.env`, the root of that environment's checkout, two levels above the
compose file: the deploy passes `--env-file` explicitly and never rsyncs one.

The first administrator, once the stack is up:

```
docker compose -p orbiters exec api uv run --no-sync orbiters createadmin --email you@example.com --nome "Nome Cognome"
```

Asks for the password on the terminal, twice, and never takes it as an argument.

## Deploy

`.github/workflows/deploy-hub.yml`: preview on a push to `main` that touched the hub,
production on a tag `hub-v<semver>` (`hub-v0.1.0` is out already). Both call the
shared `_deploy-compose.yml`. The production compose project is `orbiters`, not
`hub` — the name the stack first went up under by hand on 2026-09-09 (ORB-17), since
a different name here would start a second stack beside the running one. The
preview's is `orbiters-preview`. `GET /health` touches the database on purpose, so a
green deploy means Postgres is up and migrated, not only that uvicorn answered.

## Status

Shipped: `hub-v0.1.0` is deployed. What is still open — CV retention, the privacy
paragraph the wizard has to link before the CV step, whether the signup-listing MCP
tool moves out of PigroCRM's server — and the decisions taken with Ivan are in
[`docs/superpowers/specs/`](docs/superpowers/specs/).
