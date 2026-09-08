#!/usr/bin/env sh
# Dump completo del database PigroCRM sull'host, con data nel nome. Da lanciare a mano o da
# cron/launchd; tiene gli ultimi 30 dump. Legge POSTGRES_* dal .env accanto allo script.
set -eu
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
DEST="${PIGROCRM_BACKUP_DIR:-$(dirname "${PIGROCRM_DATA_DIR:-./data/postgres}")/backups}"
mkdir -p "$DEST"
FILE="$DEST/pigrocrm-$(date +%Y%m%d-%H%M%S).sql"
docker exec pigrocrm-db pg_dumpall -U "${POSTGRES_USER:-pigrocrm}" > "$FILE"
ls -1t "$DEST"/pigrocrm-*.sql | tail -n +31 | xargs -r rm --
echo "backup scritto: $FILE ($(du -h "$FILE" | cut -f1))"
