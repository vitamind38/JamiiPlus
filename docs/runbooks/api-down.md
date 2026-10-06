# API down (or disk filling)

**Effect:** CHPs' apps keep reports on the phone and retry; SMS and USSD reports fail until it is back. Officers cannot log in.

1. `docker compose -f infra/docker-compose.yml ps` — which container is not healthy?
2. `docker compose -f infra/docker-compose.yml logs --tail=200 api` — look for a crash loop or a database error.
3. Database down? `docker compose ... logs postgres`. Disk full is the usual cause: `df -h`; prune old images with `docker image prune` (keep the previous release's images).
4. Bad release? `infra/scripts/deploy.sh --rollback`.
5. Once healthy, check `/readyz`, then tell the county officer and CHAs how long reporting was affected.
