#!/usr/bin/env bash
# Brings up a disposable database, migrates it, seeds the admin the E2E specs log
# in as, and starts the API. Idempotent: safe to run again on top of a previous,
# still-running stack (it recreates the container and re-launches the API).
#
# Deliberately independent of whatever else is running on this machine: the
# container name, Postgres port (55433, not the default 5432) and database name
# are all suffixed "-e2e" precisely so this can run next to a developer's own
# Postgres, or next to the manual "Stack recipe" from the task brief, without
# either one seeing the other.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

# shellcheck source=./e2e-env.sh
source "$REPO_ROOT/apps/web/scripts/e2e-env.sh"

echo "== pigrocrm e2e: bringing up Postgres on :$PIGROCRM_E2E_PG_PORT =="
docker rm -f "$PIGROCRM_E2E_CONTAINER" >/dev/null 2>&1 || true
docker run --rm -d --name "$PIGROCRM_E2E_CONTAINER" \
  -e POSTGRES_PASSWORD=pigrocrm -e POSTGRES_USER=pigrocrm -e POSTGRES_DB=pigrocrm_e2e \
  -p "$PIGROCRM_E2E_PG_PORT":5432 postgres:17-alpine >/dev/null

echo "== pigrocrm e2e: waiting for Postgres to accept connections =="
until docker exec "$PIGROCRM_E2E_CONTAINER" pg_isready -U pigrocrm >/dev/null 2>&1; do sleep 1; done

echo "== pigrocrm e2e: running migrations =="
(cd packages/core && uv run alembic upgrade head)

echo "== pigrocrm e2e: seeding the admin the specs log in as, and the default pipeline =="
uv run python - <<'PY'
from pigrocrm.core.actor import Actor
from pigrocrm.core.auth.schemas import UserCreate
from pigrocrm.core.auth.service import UserService
from pigrocrm.core.config import get_settings
from pigrocrm.core.db import create_engine_from_settings, session_factory
from pigrocrm.core.pipeline.service import PipelineService

engine = create_engine_from_settings(get_settings())
with session_factory(engine)() as session:
    UserService(session).create(
        UserCreate(email="e2e@pigro.it", password="supersegreta1", nome="E2E", ruolo="admin"),
        Actor.system(),
    )
    # `seed_defaults` is admin-only as of this codebase's own Task 15 review (it now
    # calls `actor.require_admin` itself, not just the REST router) -- the brief's own
    # sample called this with no `actor` at all, which `PipelineService.seed_defaults`
    # no longer accepts. `Actor.system()` is the same actor `createadmin` and this
    # script's own user-seeding step above already use.
    PipelineService(session).seed_defaults(Actor.system())
print("seed completato")
PY

echo "== pigrocrm e2e: starting the API on :$PIGROCRM_E2E_API_PORT =="
nohup uv run uvicorn pigrocrm_api.main:app --port "$PIGROCRM_E2E_API_PORT" \
  >"$PIGROCRM_E2E_API_LOG" 2>&1 &
echo $! >"$PIGROCRM_E2E_API_PIDFILE"

echo "== pigrocrm e2e: waiting for the API to answer =="
for _ in $(seq 1 60); do
  if curl -fsS "http://localhost:$PIGROCRM_E2E_API_PORT/openapi.json" >/dev/null 2>&1; then
    echo "stack pronto su :$PIGROCRM_E2E_API_PORT (pid $(cat "$PIGROCRM_E2E_API_PIDFILE"))"
    exit 0
  fi
  sleep 1
done

echo "L'API non ha risposto in tempo. Log:" >&2
cat "$PIGROCRM_E2E_API_LOG" >&2 || true
exit 1
