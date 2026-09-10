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
    if: ${{ !cancelled() && (needs.changes.outputs.all == 'true' || needs.changes.outputs.<name>_py == 'true') }}
    uses: ./.github/workflows/_python-gate.yml
    with:
      lint-path: projects/<name>
      sources: projects/<name>/apps/api/src
      tests: projects/<name>/apps/api/tests
```

Then add the new job to `ci`'s `needs:` list. Forgetting that is the failure that
does not look like one: the job runs, it can go red, and `ci` stays green.

Copy that `if:` exactly; both halves earn their place. `!cancelled()` keeps the job
alive when a job it needs was skipped, because a skipped dependency skips the
dependent whatever its own `if` says, and skipped counts as passing. `outputs.all`
is the push whose base commit could not be reached, where the honest answer to
"what changed" is everything.

**A project that ships an image needs its own image filter**, listing what the build
context actually copies in: the project's own tree, `shared/**` if it uses it, and
the root manifests (`package.json`, `pnpm-lock.yaml`, `pyproject.toml`, `uv.lock`,
`.dockerignore`). The trunk tier is scoped like the PR tier since 2026-09-09, so a
filter that is missing means an image that stops being built rather than one that is
built too often, and the deploy will happily ship the last one that was.

**A project that deploys needs a `<name>_deploy` filter too**, which is that image
filter plus the two workflow files that decide the deploy. Write it with the YAML
anchor the existing three use (`&<name>_image` on the image filter, `*<name>_image`
in the deploy one) rather than a second copy of the paths: `changes` publishes these
three as the `changed-paths` artifact and each deploy reads its own key from it, so a
drifted copy is a project that stops deploying. It happened the other way round
before 2026-09-09, when each deploy carried its own grep and PigroCRM's had lost
`shared/brand`.

## 6. Preflight

Add the project's expensive checks to `.github/preflight.json`, with `when` globs
scoped to `projects/<name>/**`. Mark `serial: true` anything that binds a fixed host
port or a shared database — this box runs several agents at once and a port
collision reads exactly like a failing test. Then run `preflight --list` and read
which checks your diff actually selects, rather than assuming the globs are right.

**Anything you took off the PR path has to appear here.** A heavy check in neither
tier is a hole, not a saving.

## 7. Deploy

Two environments, two triggers, and no deploy logic of your own:

- **preview** when CI concludes green on `main` for a commit that touched the project;
- **production** on a version tag, `<name>-v<semver>`, never on a branch.

A bare `v1.2.0` cannot work here: it does not say which project it releases. The tag
is project-scoped for the same reason the directory is.

The tag is also a push `ci.yml` listens to (`tags: ['*-v*']`), so it earns a full CI
run of its own, every job, and `_deploy-compose.yml` gates the production deploy on
that run rather than on the trunk's run for the same commit. The trunk tier is
path-scoped: a docs-only commit after a red change to your project gets a trunk run
where every one of your jobs is skipped and `ci` concludes success, and a tag on that
commit would otherwise ship the red code. The price is one full run per release.

The mechanism lives in `.github/workflows/_deploy-compose.yml` and is shared. What a
project writes is a caller, `deploy-<name>.yml`, with one job per environment, each
naming four things: the GitHub environment, the compose directory, the compose project
name, and a health URL. Copy `deploy-pigrocrm.yml`; it is deliberately short.

The preview trigger is `workflow_run` on CI, not `push`, because the deploy refuses an
unverified commit and waiting for CI on a billed runner cost more than the deploy
itself (measured 2026-09-09: 458 of 514 seconds). Two things follow, and the copied
file already does both. The preview job passes `ref: ${{ github.event.workflow_run.head_sha }}`,
since `github.sha` on that event is the branch tip at event time and can already be a
commit CI never saw. And a `workflow_run` workflow always runs in its default-branch
version, so a change to one of these files cannot be exercised from a branch: land it
and watch the next trunk push.

Three rules that are easy to get wrong and expensive to debug:

1. **`secrets: inherit` on both jobs.** A reusable workflow reads an environment's
   secrets only when the caller inherits. Without it every `DEPLOY_*` secret is the
   empty string, silently. `_deploy-compose.yml` fails loudly on that, by design.
2. **Never let compose derive its project name.** Pass `-p`. Otherwise the name comes
   from the directory, and moving the project in the repository orphans the running
   stack and starts a second one beside it.
3. **A health URL that touches the database.** An endpoint answering from
   configuration alone reports a healthy deploy with Postgres on the floor.

### Where the per-environment configuration lives

In **GitHub Environments**, named `<name>-preview` and `<name>-production`, each
holding the same four secrets: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PATH`,
`DEPLOY_SSH_KEY`. Always those four names. Ten projects with two environments each are
forty secrets and four names, instead of forty names to remember. Environments also
give the Deployments tab a real per-environment history, and they are where a required
reviewer on production goes the day the account is on a paid plan.

```
gh api -X PUT repos/joinorbiters/<repo>/environments/<name>-preview
gh secret set DEPLOY_HOST --env <name>-preview --body '...'
```

The deploy stays off until its arming variable exists:
`vars.<NAME>_PREVIEW_ENABLED` and `vars.<NAME>_DEPLOY_ENABLED`, both `'true'` to run.
A fresh repository has neither, so nothing deploys by accident.

### What the host needs

One directory per environment, `DEPLOY_PATH`, each with its own `.env`, its own data
directory, its own ports, and its own compose project name. The `.env` is never in the
repository and never rsynced: the deploy excludes it.

**The `.env` is `${DEPLOY_PATH}/.env`**, at the root of the environment's checkout and
two levels above the compose file. The deploy passes `--env-file "${DEPLOY_PATH}/.env"`
explicitly, which replaces compose's default lookup beside the compose file: a `.env`
in `projects/<name>/` on the server is not read. Write that same location in the
project's `.env.example` and `AGENTS.md`, and put every variable the compose file
requires there, the data directory included. Give the data directory no default in the
compose file (`${<NAME>_DATA_DIR:?}`): a `.env` that forgets it then fails the stack,
where a relative default brings Postgres up on an empty directory with the health check
answering 200 and the real rows unmounted. A build interpolates the whole file, so the
image jobs in `ci.yml` and `preflight.json` pass a throwaway value for it.

Two environments on one host must share nothing but the host, which for PigroCRM means
separate databases, separate secrets, and no production Google credentials in preview.

### Taking something over from another project

When a project starts serving what another one served, the order is not a preference.
**The new deployable goes up and takes the name first; only then does the old one stop
building it.** Landing them the other way round leaves a window where the name points
at a container that no longer has the pages, and on this repository that window was not
theoretical: while production was still deployed from `main` by hand, a merge was
effectively a release whatever the tag policy said. It cost twenty minutes of a
redirecting joinorbiters.com on 2026-09-09 (ORB-16). Since that afternoon nothing is
deployed by hand (`docs/design/DECISIONS.md`, 2026-09-09): production moves only on a
tag, so the order above is what makes the tag safe to push.

The reverse direction is free: a new container that nobody points at yet can be
deployed, curled and left running for as long as you like.

### If the project answers on a public name

The host's nginx vhost belongs to the project, in `projects/<name>/deploy/`, and it
decides only what is not the project's container: everything else proxies to it and the
container owns its own path map. Every stack publishes on the loopback and never on
`0.0.0.0`: the host's nginx is what faces the internet, and publishing wider walks past
the firewall. One host carries every environment of every project, so the ports are
allocated here and nowhere else; a new project takes the next free ones and adds its
rows.

| Project | Production | Preview |
|---|---|---|
| PigroCRM | web 8080, Postgres 55432 | web 8081, Postgres 55434 |
| website | web 8082 | web 8083 |
| hub (`orbiters`, `orbiters-preview`) | api 8084, web 8085, Postgres 55435 | api 8086, web 8087, Postgres 55436 |

Since 2026-09-10 preview has public names too: `preview.joinorbiters.com` mirrors the
website plus hub map, `preview.pigro.joinorbiters.com` mirrors the CRM's, and both are
behind HTTP basic auth against `/etc/nginx/.htpasswd-preview` with
`X-Robots-Tag: noindex` on every answer. So a new project's preview gets a vhost as
well as a production one, the two files stay the same shape, and only the ports differ.
Three rules that are the reason it is safe: the password file lives on the server and
never in the repository, the credential itself is in the password manager and not in an
issue or a commit, and a preview name only ever proxies preview containers, so a click
inside preview cannot walk out into production data.

TLS on the preview names is a **certificate of their own**, `preview.joinorbiters.com`,
covering both of them, rather than two more names on the production certificate. The
reason is blast radius: `certbot --nginx --expand` reinstalls the certificate into every
vhost whose `server_name` it matches, which means it rewrites the two production files
to add a preview name, and those are the files that are edited in place. A separate
certificate touches only the two preview vhosts and renews on its own. Renewal was
dry-run through the basic auth on 2026-09-10 and passes, because the challenge path is
`auth_basic off`.

The copy in the repository is plain HTTP and is the source of truth for what the rules
are. The copy in `/etc/nginx/sites-available/` has certbot's port-443 block on top of
it: **edit that one in place**, with `nginx -t` before the reload. Overwriting it from
the repository takes TLS away on the spot.

## 8. Documentation

`projects/<name>/README.md` and `projects/<name>/AGENTS.md`, plus a row in the
project table in the root `README.md`.

## 9. Its place in Linear

Linear is the tracker and `docs/tracker.md` is the contract: initiatives, projects,
milestones, statuses, the two label groups and the loop an issue goes through are all
defined there, checked against the board, and this page does not carry a copy of them
because a copy drifts, which is exactly what an earlier version of this section did
(ORB-45). What a new monorepo project needs is an initiative of its own, named as the
directory reads to people (`PigroCRM`, not `pigrocrm`) and created by hand in the Linear
UI since the MCP surface cannot create one, and a first project under it with a scope
that can actually close, a lead and both members (the members in the UI too, since
`save_project` has no field for them), plus its row in the project table of
`docs/tracker.md` § Where things are in the same change: the initiative is the permanent
container, the project is the release. Repository-wide work that belongs to no product
(CI cost, the licence, this documentation) goes under the `Monorepo` initiative; it went
into `Monorepo hygiene v1`, which sat under no `projects/<name>/` and is closed, and
where such an issue goes now is that same section of the tracker page. The `Area`
group is shared by everyone: if the new project needs an `area:*` child the board does
not have, add it under the group rather than inventing a parallel scheme, and record it
in `docs/tracker.md` in the same change.
