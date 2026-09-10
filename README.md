# Orbiters

The monorepo for Orbiters' products.

## Projects

| Project | What it is | Stack |
|---|---|---|
| [`projects/pigrocrm`](projects/pigrocrm) | PigroCRM — an AI-first CRM for Italian freelancers, consultants and small startups. Everything the web UI can do is also reachable over REST and over MCP. | Python · FastAPI · SQLAlchemy · PostgreSQL · React · Vite |
| [`projects/website`](projects/website) | joinorbiters.com — the public site: the Orbiters community page, the pages the product signs itself with, and the signup form. Static pages, deliberately no framework. | HTML · CSS · Vite |
| [`shared/brand`](shared/brand) | The palette, the typeface and the four-tile mark, read by both surfaces so there is one source and no copy. | CSS |

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
shared/<name>/      code and assets used by more than one project
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

[GNU AGPL v3](LICENSE), chosen on 2026-09-10 when this repository went public.
Self-hosting is free; anyone who runs a modified version as a network service has to
offer that version's source to its users. Copyright stays with the authors.
