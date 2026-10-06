# Backups

Nightly: `infra/scripts/backup.sh` (host cron, 01:15). Both databases, `pg_dump -Fc`, encrypted with `age`, copied to a second Kenyan location with `rclone`. Raw audio is not backed up on purpose.

## Alert: BackupMissing / BackupMetricAbsent
1. `grep backup /var/log/syslog` or run the script by hand and read the error.
2. Common causes: `age`/`rclone` missing on the host, remote credentials expired, disk full.

## Restore test (before launch, then monthly)
`AGE_IDENTITY=/secure/key.txt infra/scripts/restore_test.sh /var/lib/jamii/backups/jamii-<stamp>.dump.age`

| Date | Dump | Result | By |
|---|---|---|---|
| | | | |

The private key is held offline by two named people. Losing it makes every backup useless.
