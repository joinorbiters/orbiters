# AGENTS.md — working in the Orbiters monorepo

Orientation for agents and for humans. Read this before touching anything at the
root. Facts that are true of one project only live in that project's own
`projects/<name>/AGENTS.md`, which is the file you should also read when you work
there — both Claude Code and omp load the nearest one.

## What this repository is

One repository for every Orbiters project. PigroCRM is the first of them and, today,
the only one; it is a project in here, not the point of the place. Projects are
allowed to use different stacks, and are expected to share as much of their
dependency graph and their tooling as they honestly can.

```
projects/<name>/     everything one project owns: its apps, its packages, its docs,
                     its Dockerfiles, its compose file, its deploy scripts
shared/ts/<name>/    TypeScript libraries used by more than one project
shared/py/<name>/    Python packages used by more than one project
tooling/<name>/      configuration shared by every project
docs/                documentation about the monorepo itself, never about a project
```

`shared/` does not exist yet, and a directory is not created before something real
goes in it. The workspace globs already point at those paths so that the first shared
package lands where `docs/adding-a-project.md` says, instead of wherever it is
invented.

## The dependency rule, which is the whole reason these projects live together

**One `uv.lock` and one `pnpm-lock.yaml`, both at the root.** Two projects resolving
SQLAlchemy or TypeScript twice, at two versions, is the thing a monorepo exists to
make impossible.

- **Python**: `pyproject.toml` at the root is the uv workspace. Its `members` list
  names every package one by one rather than globbing, because `projects/*/apps/*`
  also matches `apps/web` — a Vite app with no `pyproject.toml` — and uv refuses to
  start on a member without one.
- **Node**: `pnpm-workspace.yaml` globs, because pnpm ignores a directory with no
  `package.json`. Its `catalog:` block is the single source of truth for
  build-and-test toolchain versions. A package writes `"typescript": "catalog:"`.
  **What a project ships to its users stays in that project's own `package.json`**;
  what it needs in order to be built, linted and tested belongs in the catalog.

One resolution means one version of a library for everybody. That is the point, and
it has a cost: a project that genuinely needs an incompatible pin has to leave the
workspace and carry its own lock. That is an exception with a reason written down,
never a default.

## Commands

Everything runs from the repository root.

```
uv sync --frozen                       # one virtualenv for every Python package
uv run ruff check projects/pigrocrm    # lint one project
uv run mypy                            # every Python source root (see [tool.mypy] files)
uv run pytest -q projects/pigrocrm/packages/core/tests   # narrow to what you touched

pnpm install --frozen-lockfile
pnpm --filter web lint
pnpm --filter web test
```

`pytest`'s `testpaths` and `mypy`'s `files` are at the root and name each project's
paths in full. Both resolve relative to the working directory rather than to the file
they are written in, which is why there is no per-project config file to `cd` into:
that only works when you happen to be in the right place, and silently checks
nothing when you are not. Narrow to one project by passing its paths as arguments.

`ruff` is the exception, because it really does resolve per file: the root
`ruff.toml` is the monorepo-wide style and each project extends it.

## Verification: three tiers, and where each check lives

1. **Local, before the PR exists** — `.github/preflight.json`. Everything expensive:
   the full Python suite, Playwright, the images. `preflight --list` prints what your
   diff selects before you trust it; `preflight --install-hook` runs it on push.
2. **`pull_request`** — one cheap gate per project, scoped by `dorny/paths-filter`.
3. **`push` to `main`** — everything, unconditionally.

**A check that stops running on a PR must appear in `preflight.json`.** Verification
did not get cheaper, it moved; a heavy check in neither tier is a hole.

`ci` is the aggregate job and the only status check this repository should ever be
asked to require. Every other job name can change forever without a ruleset edit.
Two traps that fail silently, both already handled in `ci.yml` and both worth
knowing before you edit it:

- A job that `needs` a skipped job is skipped too, **whatever its own `if` says**,
  unless that `if` contains a status-check function. `changes` is PR-only, so without
  `!cancelled() &&` the whole suite skips on the trunk and `ci` reports **green**.
- Never put a `paths` filter on `on:`. A workflow that does not run reports no
  contexts, and the PR becomes unmergeable rather than passing.

Adding a project means adding one filter to `changes` and one or two jobs that call
`_python-gate.yml` / `_node-gate.yml`. It must not mean another CI workflow file. A
deploy workflow, on the other hand, is per project and named after it, so that two
projects can never deploy each other by accident.

## Conventions

- **Conventional Commits**, in English, in the first person, written the way a person
  writes. No em dashes, no "not just X but Y", no emoji. The same goes for PR
  descriptions and issue bodies.
- **Never add an AI co-author trailer** to a commit or a PR, in any form.
- **No absolute paths** in committed code or tests. Derive them.
- Repo-facing text is English. User-facing strings stay in the language the product
  speaks, which for PigroCRM is Italian. The existing Italian design documents under
  `projects/pigrocrm/docs/` are not being translated: they are a record of decisions
  already taken.
- A design decision that is a rule rather than a picture goes in
  `docs/design/DECISIONS.md`, as a row, with the date.

## What a human decides, not you

The repository's licence and whether it goes public, the repository's name and owner,
domains, anything a client will read, and any production deploy or store submission.
Ask. Everything a tool or the repository itself can answer, look up instead of asking.
