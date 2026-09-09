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
shared/<name>/       code or assets used by more than one project
tooling/<name>/      configuration shared by every project
docs/                documentation about the monorepo itself, never about a project
```

`shared/brand` is the first of those and shows what belongs there: the palette, the
typeface and the brand mark, which the CRM and the website must agree on and neither
can own. A project small enough to be a single artifact may be one package at its own
root rather than growing an `apps/` directory with one entry in it, which is what
`projects/website` is. `tooling/` is still empty, and a directory is not created
before something real goes in it.

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
3. **`push` to `main`** — the heavy tier (the corpus, the images), scoped by the
   same filters. It was unconditional until 2026-09-09, when the measurement said
   1,564 hosted minutes in eight days against a 2,000/month allowance on a private
   repository. A push that cannot reach a project does not pay for that project's
   suite. When a push has no reachable base commit the filters are skipped and
   everything runs, and so does a release tag (`<project>-v<semver>`, which `ci.yml`
   also listens to): a production deploy is gated on the run of the tag itself, since
   the trunk's run for the same commit may have skipped every job of that project and
   still concluded green. The `changes` job also publishes its verdict as the
   `changed-paths` artifact, which is what each deploy reads instead of recomputing
   the same paths for itself.

**A check that stops running on a PR must appear in `preflight.json`.** Verification
did not get cheaper, it moved; a heavy check in neither tier is a hole.

**Two things about the Python suite, measured on 2026-09-09 and easy to undo by
accident.** It is deselected by marker into two jobs that run side by side: the
`slow` corpus is twelve minutes of PostgreSQL around two files, so merging it back
into the main gate puts the sum back on the critical path. And the rest runs under
`-n auto --dist loadfile`, which works because each xdist worker starts its own
container from the session-scoped fixture; `loadfile` is what keeps a file's tests
on one worker, as the module-scoped fixtures require. A test that only passes in
alphabetical order fails here, which is the point: four did, and they were fixed
rather than pinned. The corpus job stays serial on purpose, since every assertion
in it is about which plan the planner picks and load changes the answer.

`ci` is the aggregate job and the only status check this repository should ever be
asked to require. Every other job name can change forever without a ruleset edit.
Two traps that fail silently, both already handled in `ci.yml` and both worth
knowing before you edit it:

- A job that `needs` a skipped or failed job is skipped too, **whatever its own `if`
  says**, unless that `if` contains a status-check function. `changes` runs on every
  event now, but the day it fails, `!cancelled() &&` is what keeps the suite running
  instead of skipping it wholesale while `ci` reports **green**.
- Never put a `paths` filter on `on:`. A workflow that does not run reports no
  contexts, and the PR becomes unmergeable rather than passing.

Adding a project means adding one filter to `changes` and one or two jobs that call
`_python-gate.yml` / `_node-gate.yml`. It must not mean another CI workflow file.

**Deploy is a fourth thing, and it is not a status check.** Two environments per
project: preview when CI concludes green on `main` for a commit that touched the
project, production only on a project-scoped tag, `<project>-v<semver>`. **Never by
hand**: no `docker compose up`, `rsync` or `git pull` on the server is a release, for
any stack in any environment (`docs/design/DECISIONS.md`, 2026-09-09); a deploy that is
not armed gets armed. The mechanism is shared (`_deploy-compose.yml`); the trigger is
per project (`deploy-<project>.yml`), so two projects can never deploy each other by
accident.
Per-environment configuration is a **GitHub Environment**, holding the same four
secrets everywhere: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PATH`, `DEPLOY_SSH_KEY`.
The caller must pass `secrets: inherit`, or a reusable workflow reads all four as
empty strings. Both environments stay off until their arming variable exists. The
runbook is `docs/adding-a-project.md` §7.

**The preview triggers on `workflow_run`, and that is a cost decision with two
consequences worth knowing.** It used to trigger on the push and then poll the API
until CI finished, on a billed runner: measured on 2026-09-09, 458 of 514 billed
seconds were that sleep and 51 were the deploy. Since the trigger is now CI's own
completion, first: `github.sha` on that event is the branch tip when the event fired,
not the commit that was verified, so the caller passes
`github.event.workflow_run.head_sha` as the `ref` input and `_deploy-compose.yml`
checks out, verifies and records that. Second: a `workflow_run` workflow only ever
runs in the version on the default branch, so a change to a deploy file cannot be
tested on a branch and is proven on the trunk instead.

## Conventions

- **Conventional Commits**, in English, in the first person, written the way a person
  writes. No em dashes, no "not just X but Y", no emoji. The same goes for PR
  descriptions and issue bodies.
- **Never add an AI co-author trailer** to a commit or a PR, in any form.
- **No absolute paths** in committed code or tests. Derive them.
- **Everything in this repository is written in English.** Documentation, READMEs,
  code, comments, docstrings, test names, commit messages, pull requests, and
  everything written into Linear: issue titles, descriptions, comments and project
  updates. No exceptions for "just this one file": a repository half in one
  language is one nobody can hand to a contributor, and this one is meant to be
  open-sourceable.

  The line, and it is the only one: **what the product says to its users stays in the
  user's language**, which for PigroCRM is Italian. That means the strings a person
  reads or hears, not the code around them: UI copy, validation and error messages,
  the OpenAPI descriptions rendered on the public docs page, every MCP tool, prompt
  and resource description (an assistant reads those out to an Italian freelancer),
  document templates and seeded content. When you cannot tell whether a docstring is
  documentation or product surface, check whether a framework publishes it: a
  `@mcp.tool()` or a FastAPI `description=` is the product speaking.

  Two things are grandfathered, deliberately. The dated design records under
  `projects/pigrocrm/docs/superpowers/` are a verbatim record of decisions already
  taken and are not retranslated: rewriting a record is how a record stops being one.
  Anything written from now on, there included, is English.
- A design decision that is a rule rather than a picture goes in
  `docs/design/DECISIONS.md`, as a row, with the date.
- **The tracker is Linear, and using it is not optional.** Team `Orbiters`, issue
  prefix `ORB-`. Work that is not on the board did not happen, for either of us or
  for any agent either of us runs, and there is no second tracker: the GitHub
  issues and any GitHub Project on other repositories are not part of this repo's
  flow.
- Four levels, in order. An **initiative** is a product and is permanent: four
  exist today (`Website`, `Hub`, `PigroCRM`, `Monorepo`). A **project** is a
  release, or a body of work with an end, and it closes when it ships. A **project
  milestone** is a coherent outcome inside a release, not an issue: epics are never
  modelled as issues. An **issue** is one agent run, one PR, one worktree. The rest
  of the convention, from what a title says to which labels are legal, is in
  `docs/tracker.md`.
- **Every project always carries a lead and both members.** A project created
  without a lead and without both members is incomplete.
- **The assignee is a claim, and a card that is not yours stays untouched.** Both of
  us run agents against the same board, so the only thing keeping two of them off
  the same work is that field: you may work a card assigned to the account your
  session writes as (`get_user` with `"me"`, checked once per session), a card with
  no assignee that you filed yourself, or a card labelled `parallel` that nobody has
  claimed. Anything else gets a comment at most, never an assignee change, a status
  change, a branch or a PR, and being asked for it by name does not make it yours
  (`docs/tracker.md` § Who owns a card). Every issue is filed with an assignee for
  the same reason: an empty one reads as free.
- An issue carries exactly one `type` label and exactly one `area:*` label, both from
  enforced groups, so Linear drops a second one silently. Priority and effort are
  Linear's native fields and are never labels.
- `In Review` is a status on the team, and it is where an issue sits while its PR
  is open on GitHub.
- **A project update is written whenever something changed that the issue list
  alone does not show**: a milestone slipped, a health change, a decision, a
  release. An update that only restates the board is noise.
- Linear's GitHub app is requested and pending on this org; only the org owner can
  approve it, so nothing closes itself yet. An issue reference in a commit body is
  a pointer, not a link: the state is still moved by hand, with the evidence in a
  comment.

Find the issue before you start, check it is yours, move it as you go, and close it
only against evidence on the surface it is about. A defect you found and did not fix
gets filed before you finish.

## Skills an agent is handed

`.claude/skills/` holds the procedures an agent needs at a precise moment, so they are
not left to memory: `pr-creation` (branch, title, body, review and merge loop, the
hand-off to Linear), `linear-ticket` (the board workflow in one `save_issue` call, the
state changes, the API quirks) and `linear-content` (how an issue, a comment, a closing
comment or a project update is written here). They point at this file,
`docs/tracker.md`, `.github/PULL_REQUEST_TEMPLATE.md` and `docs/design/DECISIONS.md`
and restate as little of them as they can: the documents are the contract, the skills
are the order of operations, and where the two disagree the skill has the bug.

## What a human decides, not you

The repository's licence and whether it goes public, the repository's name and owner,
domains, anything a client will read, and any production deploy or store submission.
Ask. Everything a tool or the repository itself can answer, look up instead of asking.
