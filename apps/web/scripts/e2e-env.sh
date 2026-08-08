# Shared constants for the E2E scripts (e2e-setup.sh / e2e-teardown.sh / e2e.sh).
# Sourced, never executed directly -- every value here has to land as an exported
# variable in the *caller's* shell, not in a short-lived subshell of its own.
#
# `e2e.sh` sources this itself (in addition to calling e2e-setup.sh, which sources
# it a second time inside its own process) specifically so the top-level Playwright
# `test` process it launches inherits PIGROCRM_DATABASE_URL/PIGROCRM_JWT_SECRET too --
# `e2e/resilience.spec.ts` needs both in `process.env` to relaunch uvicorn itself
# after deliberately killing it mid-suite. Sourcing the same file from both places
# is what keeps the two copies from ever drifting apart.
#
# Lives under apps/web/ (not a repo-root scripts/, which is what the task-10 brief's
# own sample used) because this task's own binding rule is narrower than the brief
# it started from: "Only apps/web/ may change" -- this worktree is one of several
# sibling slices sharing the same repo, and a repo-root scripts/ is exactly the kind
# of shared directory that would collide with another one on merge. Every *value*
# below is still the brief's own, verbatim; only the path holding them moved.

export PIGROCRM_DATABASE_URL="postgresql+psycopg://pigrocrm:pigrocrm@localhost:55433/pigrocrm_e2e"
# The brief's own literal value here ("e2e-secret-not-for-production") is 29
# characters -- one short of `MIN_JWT_SECRET_LENGTH = 32`
# (packages/core/src/pigrocrm/core/config.py). `Settings`' own field validator
# rejects anything shorter at import time, so the API would fail to even start
# with that exact string: confirmed by trying it first. This is the same string
# with a few words appended so the requirement is actually met.
export PIGROCRM_JWT_SECRET="e2e-secret-not-for-production-but-long-enough"
# Deliberately left unset (not "false"): `cookie_secure` defaults to `true`
# (config.py), and that file's own comment on the setting says Chrome/Chromium
# treats "localhost" as a secure context and accepts a `Secure` cookie over plain
# HTTP there -- Safari is the one browser that does not, which is exactly why the
# setting exists at all. `playwright.config.ts` only ever runs the `chromium`
# project, so the default holds and this stays closer to what production actually
# runs. Verified live (see task-10-report.md): the seeded admin's login cookie is
# both set and sent back on the next request under this exact configuration.

# Exported, not merely `readonly`: e2e/resilience.spec.ts (running inside the
# Playwright *test* process, a grandchild of e2e.sh via `pnpm exec playwright
# test`) reads PIGROCRM_E2E_API_PIDFILE/PIGROCRM_E2E_API_PORT from
# `process.env` to kill and relaunch the API itself, and to know where to
# write the new pid back to for e2e-teardown.sh to find afterwards.
export PIGROCRM_E2E_CONTAINER="pigrocrm-e2e"
export PIGROCRM_E2E_PG_PORT="55433"
export PIGROCRM_E2E_API_PORT="8000"
export PIGROCRM_E2E_API_PIDFILE="/tmp/pigrocrm-e2e-api.pid"
export PIGROCRM_E2E_API_LOG="/tmp/pigrocrm-e2e-api.log"
