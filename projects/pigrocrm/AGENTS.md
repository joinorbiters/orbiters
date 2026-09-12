# AGENTS.md — working on PigroCRM

The root [`AGENTS.md`](../../AGENTS.md) covers the monorepo: layout, the single
lockfiles, the CI contract, commit conventions. This file is only about this project.
Tracker: the **PigroCRM** project in Linear, conventions in `docs/tracker.md`. File
what you find, and close nothing you have not verified.

## What it is

An AI-first CRM for Italian freelancers, consultants and small startups. It covers
the whole cycle without changing application:

```
Contatto → Cliente → Deal → Offerta → Lavoro → Time tracking → Fattura → Analisi economica
```

The design record is `docs/superpowers/specs/`, in Italian, one document per slice.
Read the spec before rewriting something that looks odd: most of what looks odd here
was decided, and the reason is written down.

## The four principles that constrain the code

- **API first.** The UI uses only the public API. No logic exists in the frontend
  alone.
- **MCP first.** `apps/mcp` is not an adapter bolted on afterwards: it calls the same
  services the UI does, in process.
- **No duplication.** Every fact is stored once.
- **Single-tenant inside, several spaces outside.** No service knows about tenants.
  Signing up from the login gets you a *space*: a Postgres database of its own with
  the same schema, served under `/<name>/app` and `/<name>/api`. The root
  installation is unchanged. See
  `docs/superpowers/specs/2026-09-08-spazi-un-database-per-tenant-design.md`.

## Layout, and the one import rule that is enforced

```
packages/core/   the domain: models, services, migrations, rendering. Depends on neither adapter.
apps/api/        FastAPI. Imports core.
apps/mcp/        the MCP server, stdio and Streamable HTTP. Imports core.
apps/web/        Vite + React SPA, served under /app.
deploy/          the nginx vhost and the server setup script.
```

The public pages are **not here**: they are their own project, `projects/website`
(joinorbiters.com and the pages the product signs itself with). Its built output is
still copied into this project's web image and served at the document root, which is
a serving arrangement and not a dependency of the application on it. The palette,
the typeface and the brand mark both surfaces use live in `shared/brand`.

**`packages/core` may import neither adapter, and neither adapter may import the
other.** This is enforced twice and both are load-bearing: `ruff.toml`'s
`flake8-tidy-imports.banned-api` at the project level, narrowed by each adapter's own
nested `ruff.toml`, and `packages/core/tests/test_architecture.py`, which builds
core's allowed-import set **by reading `[project].dependencies` in
`packages/core/pyproject.toml` literally**. Adding a runtime import to core without
declaring it there fails that test, which is the point.

## Running it

From the repository root:

```
uv sync --frozen && pnpm install --frozen-lockfile
uv run pytest -q projects/pigrocrm/packages/core/tests   # narrow to what you touched
pnpm --filter web dev
```

`docker compose` runs from this directory, and its build context is the repository
root two levels up, because that is where the lockfiles are.

## Things that will cost you an afternoon if you do not know them

**The document renderer shells out to Pandoc and Typst.** Roughly thirty tests fail
without both on `PATH`, with `strumento di composizione non installato`. The versions
that matter are pinned in `Dockerfile.api` — Pandoc 3.8.2.1 and Typst 0.14.2 — and
Typst's diagnostic format and the auto-typography workaround were verified against
0.14.2 specifically, not assumed stable across releases. CI installs the same pair.

**`cookie_secure` defaults to true and `docker-compose.yml` never overrides it for
the `api` container, deliberately.** On plain HTTP the browser silently drops the
session cookie: login answers 200 and every request after it is unauthenticated. If
you are debugging "the login works but nothing else does", this is it — and in
production it means TLS has to be configured *before* anyone tries to log in.

**`pg_trgm` is created by the migrations at API start-up.** On a managed Postgres
where the user cannot create extensions, the deploy fails at boot with
`permission denied to create extension "pg_trgm"`. That is the wanted behaviour: the
alternative is an application that starts and then scans sequentially in silence.

**The e2e ports are hardcoded, not read from the environment.**
`apps/web/scripts/e2e-env.sh` exports 55433 (its own Postgres), 8000 (the API) and
5173 (Vite) as literals, and the script clears whatever holds :8000 and :5173 before
it starts. On this shared box that is a real collision with other projects, and it is
why `pigrocrm-e2e` is `serial: true` in `.github/preflight.json`. Editing those three
values into `${VAR:-default}` form is a genuine improvement and has not been done.

**Two concurrent `pigrocrm-e2e` runs corrupt each other through the pidfile, not just
the ports.** `e2e/resilience.spec.ts` kills the API mid-suite and relaunches it,
tracking the pid through the fixed path `PIGROCRM_E2E_API_PIDFILE`
(`/tmp/pigrocrm-e2e-api.pid` by default) rather than through a per-checkout handle.
With a second run alive on the same box, `helpers.ts`'s `killApi()` can read a pid
that run already replaced or reaped and die on `kill ESRCH` at `helpers.ts:209`
instead of the test it was meant to run — observed live on 2026-09-10 with several
other agents' containers and dev servers on the same devbox, filed as ORB-91. Run
`pigrocrm-e2e` one checkout at a time; the pidfile trap does not show up any other
way.

**Migrations live in `packages/core/migrations` with `alembic.ini` beside them**, and
`tenants/service.py` finds that file from `pigrocrm.core.__file__` rather than from
the checkout, so it works identically in the image. The API container runs
`alembic upgrade head` at start-up; there is one instance, so there is no
concurrent-migration risk. That command migrates the **root** database only. After it
the same `CMD` runs `pigrocrm ensure-space-defaults`, which brings every space in the
registry to head with the same `migrate_to_head` provisioning uses (ORB-189: a space
was migrated once, at creation, and `pigrocrm-v0.13.0` broke every space's login by
shipping a migration they had never received), then gives it its default stages,
templates and cost categories where a table is empty, and never fails the boot (spec
2026-09-12 §6.5). A new migration reaches the spaces at the first boot after the deploy,
not before: nothing else runs DDL on a space.

**`--no-sync` on the container's `uv run` calls is load-bearing.** Without it, uv
re-evaluates the environment against the default group selection — which includes
`dev` — decides the image's venv is out of date, and downloads mypy and ruff into a
running production container on every start. That happened once, live.

## Namespace

Every environment variable is `PIGROCRM_*`, the CLI is `pigrocrm`, the databases and
the e2e container carry the name too. None of that is monorepo-wide: it is this
project's namespace and it stays project-scoped. `.env.example` documents every
variable and is the file to read before adding another.
