#!/usr/bin/env bash
# Nightly encrypted backup of both databases, copied to a second Kenyan location.
#
# Run from cron on the host, e.g.  15 1 * * *  /opt/jamii-pulse/infra/scripts/backup.sh
#
# Needs on the host: docker, age (https://age-encryption.org), rclone with a remote named in
# BACKUP_REMOTE that points at storage in a second Kenyan data centre.
#   BACKUP_AGE_RECIPIENT   public key; the private key is kept offline by two named people
#   BACKUP_REMOTE          e.g. ke-dc2:jamii-backups
# Raw audio is deliberately NOT backed up: it has short retention and a backup would extend it.
set -euo pipefail

cd "$(dirname "$0")/.."
: "${BACKUP_AGE_RECIPIENT:?set BACKUP_AGE_RECIPIENT}"
: "${BACKUP_REMOTE:?set BACKUP_REMOTE}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"
WORK="${BACKUP_WORKDIR:-/var/lib/jamii/backups}"
METRICS="${BACKUP_METRICS_DIR:-/var/lib/jamii/metrics}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$WORK" "$METRICS"
umask 077

for db in jamii jamii_audit; do
  out="$WORK/${db}-${STAMP}.dump.age"
  docker compose exec -T postgres pg_dump -U postgres -Fc "$db" | age -r "$BACKUP_AGE_RECIPIENT" -o "$out"
  # A dump smaller than 1 KB means something went wrong.
  [ "$(stat -c %s "$out")" -gt 1024 ] || { echo "backup of $db looks empty" >&2; exit 1; }
  rclone copy "$out" "$BACKUP_REMOTE/$(date -u +%Y/%m)/" --immutable
done

# Keep only recent local copies; the remote keeps its own retention policy.
find "$WORK" -name '*.dump.age' -mtime +"$KEEP_DAYS" -delete

# Prometheus (node-exporter textfile collector) alerts if this stops moving.
echo "jamii_backup_last_success_timestamp_seconds $(date +%s)" > "$METRICS/backup.prom.tmp"
mv "$METRICS/backup.prom.tmp" "$METRICS/backup.prom"
echo "backup ${STAMP} done"
