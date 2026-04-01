#!/bin/sh
# =============================================================================
# Daily pg_dump backup script
# Runs inside the backup sidecar container.
# Keeps 7 days of backups, then prunes older ones.
# =============================================================================

set -e

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="/backups"
FILENAME="${BACKUP_DIR}/recipedb_${TIMESTAMP}.dump"
KEEP_DAYS=7

echo "[backup] Starting dump at ${TIMESTAMP}..."

pg_dump \
  --host=db \
  --port=5432 \
  --username="${POSTGRES_USER:-recipeapp}" \
  --dbname="${POSTGRES_DB:-recipedb}" \
  --format=custom \
  --compress=9 \
  --file="${FILENAME}"

echo "[backup] Dump written to ${FILENAME}"

# Remove backups older than KEEP_DAYS
find "${BACKUP_DIR}" -name "recipedb_*.dump" -mtime "+${KEEP_DAYS}" -delete
echo "[backup] Pruned backups older than ${KEEP_DAYS} days"

echo "[backup] Done."
