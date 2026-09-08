#!/usr/bin/env bash
# Verifies the routing this slice changes against the real nginx, not the Vite dev
# server. deploy/nginx/spa.conf is not exercised by `pnpm dev` at all, so `/`,
# `/privacy`, `/termini`, `/app` and the `/login` redirect can only be proven here.
#
#   apps/web/scripts/e2e-compose.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

cleanup() {
  docker compose down -v
}
trap cleanup EXIT

# A pre-existing volume keeps its original POSTGRES_PASSWORD (residuo B6), so a
# clean start has to be an explicitly clean one.
docker compose down -v
docker compose up -d --build

for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8080/health >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS http://127.0.0.1:8080/health >/dev/null

cd "$REPO_ROOT/apps/web"
pnpm exec playwright test --config playwright.compose.config.ts
