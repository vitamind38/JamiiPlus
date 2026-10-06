# API errors above 5%

1. Open Sentry for the newest error group (no personal data is sent there).
2. `docker compose ... logs --tail=500 api | grep -i error`.
3. Errors only on `/channels/`? Africa's Talking may have changed a callback field; compare the request with `routers/channels.py`.
4. Started with a deploy? Roll back: `infra/scripts/deploy.sh --rollback`.
