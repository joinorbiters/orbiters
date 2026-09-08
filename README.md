# Orbiters

The monorepo for Orbiters' products.

## Projects

| Project | What it is | Stack |
|---|---|---|
| [`projects/pigrocrm`](projects/pigrocrm) | PigroCRM — an AI-first CRM for Italian freelancers, consultants and small startups. Everything the web UI can do is also reachable over REST and over MCP. | Python · FastAPI · SQLAlchemy · PostgreSQL · React · Vite |

## Getting started

Requires Python 3.13, Node 22 and Docker. [uv](https://docs.astral.sh/uv/) and
[pnpm](https://pnpm.io/) manage the two toolchains; pnpm's version is pinned in
`package.json` and corepack will honour it.

```
uv sync --frozen            # every Python package, one virtualenv
pnpm install --frozen-lockfile
```

Then follow the project you want to work on: for PigroCRM, its
[README](projects/pigrocrm/README.md) covers running it and deploying it.

## How it is laid out

```
projects/<name>/    one project: its apps, packages, docs, Dockerfiles, deploy
shared/ts|py/       code used by more than one project
tooling/            configuration shared by every project
docs/               documentation about the monorepo itself
```

There is exactly one `uv.lock` and exactly one `pnpm-lock.yaml`, both at the root, so
that two projects cannot resolve the same library at two versions.
[`docs/architecture.md`](docs/architecture.md) explains the layout and the tradeoffs
it makes; [`docs/adding-a-project.md`](docs/adding-a-project.md) is the runbook for
adding the next one.

## Contributing

[`CONTRIBUTING.md`](CONTRIBUTING.md) for the workflow and
[`AGENTS.md`](AGENTS.md) for the conventions, which apply to people and to coding
agents alike.

## Licence

Not yet chosen. Until one is added this repository is "all rights reserved" by
default, which is deliberate while it is private.
