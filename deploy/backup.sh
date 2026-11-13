#!/bin/sh
# Daily database backup on the VPS: a compressed dump in BACKUP_DIR, older than KEEP_DAYS removed.
# Run from cron as the user that owns the repository (docs/deploy.md):
#   15 3 * * * /opt/grafikomat/deploy/backup.sh >> /var/log/grafikomat-backup.log 2>&1
set -eu

cd "$(dirname "$0")/.."
BACKUP_DIR="${BACKUP_DIR:-/var/backups/grafikomat}"
KEEP_DAYS="${KEEP_DAYS:-14}"

mkdir -p "$BACKUP_DIR"
umask 077
target="$BACKUP_DIR/grafikomat-$(date +%Y%m%d-%H%M%S).sql.gz"

# Dump to a temporary name first, so a failed dump never looks like a good backup.
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' > "$target.part"
[ -s "$target.part" ] || { echo "The dump is empty." >&2; exit 1; }
gzip -c "$target.part" > "$target"
rm -f "$target.part"

find "$BACKUP_DIR" -name 'grafikomat-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
find "$BACKUP_DIR" -name '*.part' -mtime +1 -delete
echo "$(date -Iseconds) backup saved: $target"
