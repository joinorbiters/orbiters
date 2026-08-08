#!/usr/bin/env bash
# Tears down exactly what e2e-setup.sh brought up: the API process (by pidfile --
# whichever process is currently recorded there, since e2e/resilience.spec.ts
# deliberately kills and relaunches it mid-suite and rewrites the pidfile when it
# does) and the disposable Postgres container. Safe to run even if setup only got
# partway, or was already torn down -- every step tolerates "already gone".
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=./e2e-env.sh
source "$REPO_ROOT/apps/web/scripts/e2e-env.sh"

echo "== pigrocrm e2e: stopping the API =="
if [ -f "$PIGROCRM_E2E_API_PIDFILE" ]; then
  pid="$(cat "$PIGROCRM_E2E_API_PIDFILE")"
  if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid" >/dev/null 2>&1 || true
    for _ in $(seq 1 20); do
      kill -0 "$pid" >/dev/null 2>&1 || break
      sleep 0.5
    done
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi
  rm -f "$PIGROCRM_E2E_API_PIDFILE"
fi
rm -f "$PIGROCRM_E2E_API_LOG"

echo "== pigrocrm e2e: removing the Postgres container =="
docker rm -f "$PIGROCRM_E2E_CONTAINER" >/dev/null 2>&1 || true

echo "== pigrocrm e2e: torn down =="
