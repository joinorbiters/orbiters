# Adding a project

The runbook. Follow it in order; each step exists because skipping it fails somewhere
that does not name the cause.

Throughout, `<name>` is the project's directory name: lowercase, no spaces, the name
people already use for the product.

## 1. The directory

```
projects/<name>/
  apps/            deployables
  packages/        libraries this project owns and nobody else uses
  docs/            this project's own documentation, specs and notes
  README.md        what it is, how to run it, how to deploy it
  AGENTS.md        the facts an agent needs before touching it
```

A library only this project uses stays in `projects/<name>/packages/`. It moves to
`shared/` the day a second project imports it, and not before.

## 2. Wire it into the workspaces

**Node** — nothing to do for the workspace itself: `pnpm-workspace.yaml` already
globs `projects/*/apps/*` and `projects/*/packages/*`. Do point every
build-and-test dependency at the catalog:

```json
"devDependencies": { "typescript": "catalog:", "vitest": "catalog:" }
```

If a version you need is not in the catalog yet, add it there rather than pinning it
in the package. If you need a *different* version from the one in the catalog, say
why in the package.json, in a comment on the line above — a second TypeScript major
in this repository is a decision, not a detail.

**Python** — two lists in the root `pyproject.toml`, and both are required:

```toml
[tool.uv.workspace]
members = [..., "projects/<name>/apps/api"]

[project]
dependencies = [..., "<name>-api"]

[tool.uv.sources]
<name>-api = { workspace = true }
```

Then `uv lock` and commit the lockfile. Members are listed one by one on purpose:
globbing `projects/*/apps/*` also matches any Vite app, and uv refuses to start on a
member with no `pyproject.toml`.

**Every existing Dockerfile that runs `uv sync` now fails**, with "Workspace member
... is missing a `pyproject.toml`" naming your new package, because that member is
not in their build context. Add one `COPY` line to each. This is the loud half of the
tradeoff described in `architecture.md`.

## 3. Lint config

Add `projects/<name>/ruff.toml` extending the root one if the project is Python:

```toml
extend = "../../ruff.toml"

[lint.isort]
known-first-party = ["<name>"]
```

Node projects inherit nothing automatically: put the eslint config where the app
expects it, and if two projects end up with the same config, move it to
`tooling/eslint-config/` and depend on it as `workspace:*`.

## 4. Tests and types

Append the project's paths to the two lists in the root `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = [..., "projects/<name>/apps/api/tests"]

[tool.mypy]
mypy_path = [..., "projects/<name>/apps/api/src"]
files     = [..., "projects/<name>/apps/api/src"]
```

Both are root-relative, and everything runs from the root. Do not create a
`pyproject.toml` inside `projects/<name>/` for this: it is not a workspace member, a
bare `uv run` inside that directory would quietly build a second virtualenv there,
and the paths would only resolve when you happened to be standing in the right place.

## 5. CI

Two edits to `.github/workflows/ci.yml`, and no new workflow file:

```yaml
  # in the `changes` job
  outputs:
    <name>_py: ${{ steps.filter.outputs.<name>_py }}
  # ... and the matching filter block. Underscores, never dashes: a dash in an output
  # name is invalid expression syntax and the run dies with no job started.

  <name>-py:
    needs: changes
    if: ${{ !cancelled() && (github.event_name != 'pull_request' || needs.changes.outputs.<name>_py == 'true') }}
    uses: ./.github/workflows/_python-gate.yml
    with:
      lint-path: projects/<name>
      sources: projects/<name>/apps/api/src
      tests: projects/<name>/apps/api/tests
```

Then add the new job to `ci`'s `needs:` list. Forgetting that is the failure that
does not look like one: the job runs, it can go red, and `ci` stays green.

The `!cancelled()` guard is not optional. A job that `needs` a skipped job is skipped
whatever its own `if` says, `changes` is skipped on every push, and a skipped job
counts as passing.

## 6. Preflight

Add the project's expensive checks to `.github/preflight.json`, with `when` globs
scoped to `projects/<name>/**`. Mark `serial: true` anything that binds a fixed host
port or a shared database — this box runs several agents at once and a port
collision reads exactly like a failing test. Then run `preflight --list` and read
which checks your diff actually selects, rather than assuming the globs are right.

**Anything you took off the PR path has to appear here.** A heavy check in neither
tier is a hole, not a saving.

## 7. Deploy

One workflow per project, named `deploy-<name>.yml`, gated on its own
`vars.<NAME>_DEPLOY_ENABLED` variable and its own secrets. Never a shared deploy
workflow: two projects that can deploy each other by accident is a matter of when,
not whether.

## 8. Documentation

`projects/<name>/README.md` and `projects/<name>/AGENTS.md`, plus a row in the
project table in the root `README.md`.
