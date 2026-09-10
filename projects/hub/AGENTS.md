# AGENTS.md — working on the Orbiters hub

The root [`AGENTS.md`](../../AGENTS.md) covers the monorepo. This file is only about
this project.

## What it is

Orbiters, the freelance community, as a product of its own: the signup list the
community site collects, the freelancer profiles and the company requests the hub's
wizards will collect, and the admin area that reads them. Its design record is
`docs/superpowers/specs/`, English, one document per step; read the 2026-09-09 spec
before changing the shape of anything. Since 2026-09-10 a freelancer can get back in
with a magic link by mail (`/hub/accedi`, `/hub/io`): spec
`docs/superpowers/specs/2026-09-10-member-area-design.md`.

## The one rule

**Nothing here imports PigroCRM, and PigroCRM imports nothing from here.** Orbiters was
split out of the CRM on 2026-09-09 precisely so the two can change independently: its
own settings (`ORBITERS_*`), its own Postgres, its own Alembic history, its own API and
MCP server. `ruff.toml` bans the three `pigrocrm*` module roots in every package. Two
products that need to agree on something agree through `shared/`.

## Layout

```
packages/core/   orbiters_core: models, migrations, services, the ad conversion
apps/api/        orbiters_api: FastAPI, one process, its own database
apps/mcp/        orbiters_mcp: stdio, the same services in process
apps/web/        pnpm package `hub`: the SPA at joinorbiters.com/hub/ (wizards, the member area, admin)
```

`packages/core` may import neither adapter, and neither adapter may import the other:
each directory's `ruff.toml` says so.

## Running it

From the repository root:

```
uv sync --frozen
uv run pytest -q projects/hub/packages/core/tests projects/hub/apps/api/tests projects/hub/apps/mcp/tests
uv run --env-file projects/hub/.env uvicorn orbiters_api.main:app --port 8010
```

The tests bring a `testcontainers` Postgres to `head` with this package's migrations,
never with `create_all`: a table the model declares and the migration forgets fails
here rather than on the server.

**Its `vite preview` serves under `/hub/`, not `/`.** The web app is built with
`base: '/hub/'`, so the preview's root path 404s and the wizard pages are at `/hub/`,
`/hub/freelance` and `/hub/aziende`. A blank page at `/` is that, not a broken build.
Unlike the website's, this preview has no `strictPort`, so a second checkout does not
collide with the first: it takes the next free port and logs it, confirmed live as `4174`
while another agent held 4173 on 2026-09-10. Read the port off its own output rather than
assuming 4173.

## The database was inherited

`signups` was created by PigroCRM's sidecar in production and holds real rows.
Migration 0001 adopts it as it stands (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT
EXISTS`, the unique index `IF NOT EXISTS`) so the first `alembic upgrade head` on the
copied database changes nothing and records 0001. Keep every migration that may run on
that database conditional in the same way until the copy is confirmed.

## Deploying

Through CI only, as every project here (`docs/adding-a-project.md` §7): preview on a
push to `main` that touched the hub, production on a tag `hub-v<semver>`, both by
`.github/workflows/deploy-hub.yml` calling `_deploy-compose.yml`. The production compose
project is `orbiters`, the name the stack first went up under; the preview's is
`orbiters-preview`. Pass `-p` to every `docker compose` you ever run against either by
hand, or compose names a second stack after the directory.

Each environment's `.env` is `${DEPLOY_PATH}/.env`, the root of that environment's
checkout and two levels above the compose file: the deploy passes
`--env-file "${DEPLOY_PATH}/.env"`, never rsyncs a `.env`, and reads nothing beside
the compose file. It holds the `ORBITERS_*` and `POSTGRES_*` values and is never in the
repository. `ORBITERS_DATA_DIR` has no default in the compose file, so a `.env` that
forgets it fails the stack instead of mounting an empty directory.

Ports, loopback only, from the table in `docs/adding-a-project.md` §7: production api
8084, web 8085, Postgres 55435; preview 8086, 8087, 55436. The public paths are `/hub/`
(web) and `/api/hub/` + `/api/orbiters/signups` (api), proxied to production by the host
vhost that lives in `projects/website/deploy/joinorbiters.conf`; nothing proxies the
preview, which is reached on the host only. The member area's mail needs
`ORBITERS_RESEND_API_KEY` and `ORBITERS_MAIL_FROM` in the host `.env`; without the key
`/hub/accedi` answers 503 with a sentence. A preview stack that gets a key must also set
`ORBITERS_HUB_URL` to its own address, or every link it mints points at production.
