# Design decisions

One row per decision that creates a rule. A decision that is a picture belongs on a
canvas and then in a project's own documentation; this file is for the rules.

Newest last. Never rewrite a row: supersede it with a new one that says so.

| Date | Question | Answer | Rule it creates |
|---|---|---|---|
| 2026-09-08 | One repository per Orbiters project, or one for all of them? | One monorepo, with a directory per project under `projects/`. | A project owns everything under `projects/<name>/`, including its own docs, Dockerfiles and deploy scripts. |
| 2026-09-08 | Per-project lockfiles, or one per language for the whole repository? | One `uv.lock` and one `pnpm-lock.yaml`, both at the root. | Two projects can never resolve the same library at two versions. A project needing an incompatible pin leaves the workspace, with the reason written down. |
| 2026-09-08 | Where do build-and-test dependency versions live? | In `pnpm-workspace.yaml`'s `catalog:`. | A package writes `"typescript": "catalog:"`. What a project *ships* stays in its own `package.json`; what it needs in order to be built, linted and tested is monorepo policy. |
| 2026-09-08 | Do a project's design documents move to a shared `docs/` at the root? | No. They stay inside the project. | `docs/` at the root is about the monorepo only. A test that reads a note as a contract keeps working, and a project stays extractable. |
| 2026-09-08 | Per-project `pyproject.toml` for pytest and mypy configuration? | No. Both stay at the root and name each project's paths in full. | Everything runs from the repository root; CI narrows to one project by passing its paths. A config that only resolves when you have `cd`'d into a directory silently checks nothing when you have not. |
| 2026-09-08 | One CI workflow per project, or one workflow calling shared gates? | One `ci.yml`, calling `_python-gate.yml` and `_node-gate.yml` through `workflow_call`. | Adding a project costs a filter and a job, never another CI workflow. Deploy is the exception and is always per project. |
| 2026-09-08 | Which status check does the trunk require? | `ci`, the aggregate job, and only it. | Job names below `ci` can change forever without a ruleset edit. (Not yet enforceable: the org is on the Free plan and the repository is private, so rulesets are unavailable.) |
| 2026-09-08 | Rename the `PIGROCRM_*` namespace now that the repository is not just PigroCRM? | No. | Environment variables, distribution names, the CLI and the databases stay project-scoped. The project is still called PigroCRM. |
