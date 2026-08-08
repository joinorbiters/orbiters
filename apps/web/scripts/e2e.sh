#!/usr/bin/env bash
# The one documented command: brings up a disposable backend, runs the whole
# Playwright suite against it, and tears the backend back down again -- on a
# passing run, a failing run, or a Ctrl-C. Run from anywhere:
#
#   apps/web/scripts/e2e.sh
#
# or, from apps/web/: `pnpm test:e2e`.
#
# Nothing else needs to be running first: no manually-started API, no manually
# started frontend. Playwright's own `webServer` block (apps/web/playwright.config.ts)
# starts and stops `pnpm dev` around the run; this script is what does the same job
# for the one thing that config can't own -- the API and its database.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

# Sourced here too, not only inside e2e-setup.sh's own process: e2e/resilience.spec.ts
# deliberately kills the API mid-suite and relaunches it itself, which means the
# Playwright *test* process -- a child of the `pnpm exec playwright test` this script
# launches below -- needs PIGROCRM_DATABASE_URL/PIGROCRM_JWT_SECRET in its own
# environment to do that. Exporting them in this shell, before that process ever
# starts, is what makes them inherited rather than merely local to e2e-setup.sh's own
# short-lived subprocess.
# shellcheck source=./e2e-env.sh
source "$REPO_ROOT/apps/web/scripts/e2e-env.sh"

cleanup() {
  "$REPO_ROOT/apps/web/scripts/e2e-teardown.sh"
}
trap cleanup EXIT

"$REPO_ROOT/apps/web/scripts/e2e-setup.sh"

set +e
(cd "$REPO_ROOT/apps/web" && pnpm exec playwright test)
status=$?
set -e

exit "$status"
