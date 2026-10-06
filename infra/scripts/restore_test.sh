#!/usr/bin/env bash
# Prove a backup can be restored. Run before launch, then monthly. Record the result in
# docs/runbooks/backups.md.
#
#   AGE_IDENTITY=/secure/backup-key.txt infra/scripts/restore_test.sh /var/lib/jamii/backups/jamii-<stamp>.dump.age
#
# Restores into a throwaway database on the same server, checks row counts, then drops it.
# Never restore production data onto a laptop or into staging.
set -euo pipefail

cd "$(dirname "$0")/.."
DUMP="${1:?path to a jamii-*.dump.age file}"
: "${AGE_IDENTITY:?set AGE_IDENTITY to the private key file}"
TMPDB="restore_test_$(date +%s)"

docker compose exec -T postgres createdb -U postgres "$TMPDB"
trap 'docker compose exec -T postgres dropdb -U postgres --if-exists "$TMPDB"' EXIT
docker compose exec -T postgres psql -U postgres -d "$TMPDB" -c "CREATE EXTENSION IF NOT EXISTS postgis" >/dev/null
age -d -i "$AGE_IDENTITY" "$DUMP" | docker compose exec -T postgres pg_restore -U postgres -d "$TMPDB" --no-owner

docker compose exec -T postgres psql -U postgres -d "$TMPDB" -At -c "
  SELECT 'reports', count(*) FROM report UNION ALL
  SELECT 'issues', count(*) FROM issue UNION ALL
  SELECT 'responses', count(*) FROM response UNION ALL
  SELECT 'migration', version_num FROM alembic_version;"
echo "Restore test passed for $DUMP"
