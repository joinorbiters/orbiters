# AGENTS.md — working on the Orbiters hub

The root [`AGENTS.md`](../../AGENTS.md) covers the monorepo. This file is only about
this project.

## What it is

Orbiters, the freelance community, as a product of its own: the signup list the
community site collects, the freelancer profiles and the company requests the hub's
wizards will collect, and the admin area that reads them. Its design record is
`docs/superpowers/specs/`, English, one document per step; read the 2026-09-09 spec
before changing the shape of anything.

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
apps/web/        pnpm package `hub`: the SPA at joinorbiters.com/hub/ (wizards + admin)
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

## The database was inherited

`signups` was created by PigroCRM's sidecar in production and holds real rows.
Migration 0001 adopts it as it stands (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT
EXISTS`, the unique index `IF NOT EXISTS`) so the first `alembic upgrade head` on the
copied database changes nothing and records 0001. Keep every migration that may run on
that database conditional in the same way until the copy is confirmed.
