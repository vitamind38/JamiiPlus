# Jamii Pulse

A two-way channel between Community Health Promoters and the people who can fix what stops
households getting care. A CHP reports a barrier (voice note, tap, SMS or USSD), the system
understands it, an officer sees it and answers, and the CHP is told what happened.

Built from *Jamii Pulse Build Guide: Stack and Workflow* and *AI for Community Health:
Closing the CHV–Policy Gap* (6 Oct 2026). This repository is the MVP: phase 1 of the
roadmap, with phase 3's AI already wired in behind review and switched off.

```
CHP phone ──app / SMS / USSD──▶ API ──▶ PostgreSQL+PostGIS ◀── officer web app & dashboards
                                 │                                  │
                                 └─▶ Redis/Celery workers ─▶ model service (the only AI; off by default)
                                                └─▶ Africa's Talking SMS back to the CHP
```

## The rules the code keeps

- No patient-level data. Reports describe barriers, places and themes; location is ward-level.
- Everything that can hold personal data runs on one Kenyan server.
- AI only classifies, summarises and flags. A named officer sees the exact SMS before it goes.
- Low-confidence output goes to a person, never to a dashboard. Default thresholds mean
  *never auto-accept* until pilot data sets them.
- If any ML component (or the queue) is down, reporting and the response loop still work by hand.
- Every AI output links back to the raw report and records its model version.

## Repository

| Folder | Contents |
|---|---|
| `api/` | FastAPI service: CHP API, Africa's Talking SMS/USSD callbacks, officer web app (review queue, issues, dashboards, admin), Alembic migrations |
| `workers/` | Celery: assisted pipeline (redact → transcribe → classify → group), SMS retries, retention purge, weekly re-check sample, spike flags |
| `ml/` | Model service, model registry, training/evaluation/promotion scripts |
| `mobile/` | Flutter CHP app: offline-first (Drift + sync queue), Kiswahili/English, voice notes |
| `dashboards/` | Metabase setup and the SQL views it reads |
| `infra/` | Docker Compose, Caddy, Postgres roles, backups, deploy, Prometheus/Grafana |
| `docs/` | Decisions, taxonomy, DPIA template, compliance checklist, runbooks |

## Try it on a laptop (no Docker)

```bash
python -m venv .venv
.venv/Scripts/pip install -e "api[dev]" -e workers -e "ml/service[dev]"   # bin/ on macOS/Linux
python scripts/dev_server.py
```

Open http://localhost:8000 and log in as a demo officer: `0700 000 004` (county),
`0700 000 003` (sub-county), `0700 000 002` (CHA, also reviews), `0700 000 005` (reviewer),
`0700 000 001` (admin). The one-time code appears on the page in local development. Data is
synthetic; SMS are printed to the console.

## Test deployment: Vercel + Supabase

Supabase is the backend and Vercel only hosts. `api/` deploys to Vercel (project root `api/`,
entrypoint `api/vercel_app.py`, functions in Dublin). Supabase holds the data in Postgres with
PostGIS, and voice notes in a private Storage bucket, `voice-notes`. Both are in Supabase's
eu-west-1 region (Ireland).

1. **Connect the Supabase project to the Vercel project** with Supabase's Vercel integration
   (remove any other database integration first). It sets `POSTGRES_URL` (transaction
   pooler, used by the app), `POSTGRES_URL_NON_POOLING` (migrations), and `SUPABASE_URL` and
   `SUPABASE_SECRET_KEY` (Storage). `JAMII_DATABASE_URL`, `JAMII_MIGRATION_DATABASE_URL`,
   `JAMII_SUPABASE_URL` and `JAMII_SUPABASE_SECRET_KEY` override them.
2. **Settings:** `JAMII_ENVIRONMENT=staging`, `JAMII_AUTO_MIGRATE=true` (each cold start runs
   Alembic under a lock and loads the themes), `JAMII_STORAGE_BACKEND=supabase`,
   `JAMII_QUEUE_ENABLED=false`, `JAMII_PIPELINE_MODE=manual` and `JAMII_METRICS_TOKEN`, plus
   `JAMII_SECRET_KEY`, `JAMII_PSEUDONYM_KEY` and `JAMII_CHANNEL_CALLBACK_TOKEN`.
3. **First admin:** set `JAMII_BOOTSTRAP_ADMIN_PHONE` (and `JAMII_BOOTSTRAP_ADMIN_NAME`) and
   redeploy. The next cold start creates that admin if no admin exists yet. Add everyone
   else in Admin.
4. **SMS:** with `JAMII_SMS_BACKEND=console`, messages go to the Vercel runtime log with the
   phone number masked. That is enough for the admin's first login code, but not for
   testers. Before inviting testers, set `JAMII_SMS_BACKEND=africastalking`,
   `JAMII_AT_USERNAME`, `JAMII_AT_API_KEY` and `JAMII_AT_SANDBOX=false`, then switch to
   `JAMII_ENVIRONMENT=production`, which refuses console SMS.
5. **Scheduled jobs:** Vercel does not run the Celery workers, so Vercel Cron calls
   `/internal/cron/daily` (set in `api/vercel.json`) at 23:00 UTC, 02:00 in Nairobi. It runs
   the same jobs as Celery beat: deletes voice notes and text past their retention dates, old
   login codes and old SMS bodies; retries queued SMS; sends reports stuck in processing to
   people; and flags spikes if `JAMII_SPIKE_ALERTS_ENABLED=true`. Add `CRON_SECRET` to the
   project's environment variables (any long random string, type Sensitive) and redeploy.
   Vercel sends it as `Authorization: Bearer …`; without it the route answers 404 and nothing
   runs. Crons only run on the production deployment; to run one now, use **Run** in the
   project's Cron Jobs settings. Each run is in the audit log as `cron.ran`. If a job fails,
   the others still run and the route answers 500, so Vercel logs the run as failed. The Hobby
   plan allows one run a day, within the hour, so a failed SMS can wait up to a day for its
   retry. On Pro, add a cron every few minutes for `/internal/cron/frequent` (SMS retries and
   the stuck-report sweep). The weekly re-check sample does not run here: it samples what the
   model accepted on its own, and without the workers the model is never called.

The migrations turn on row-level security for every table and revoke the `anon` and
`authenticated` grants, so Supabase's public REST API exposes nothing. The app connects as
the tables' owner.

**Data location:** Supabase has no African region. Kenya's Data Protection Act restricts
moving personal data abroad, so tell testers their data is stored in Ireland and get their
consent. Real CHP reports belong on the Kenyan stack below.

## Run the real stack

```bash
cp infra/.env.example infra/.env        # fill in every secret
docker compose -f infra/docker-compose.yml up -d --build
infra/scripts/bootstrap.sh 07XXXXXXXX "Your Name"     # themes + first admin
```

Add `--profile dashboards` for Metabase and `--profile monitoring` for Prometheus, Grafana and
alerting. Point Africa's Talking's SMS, USSD and delivery-report callbacks at
`https://<domain>/channels/africastalking/{sms/inbound,ussd,sms/delivery}?token=<JAMII_CHANNEL_CALLBACK_TOKEN>`.

## Check everything

```bash
scripts/check.sh
```

Runs the personal-data guard, lint, and every test suite (API, workers, model service,
Flutter). CI does the same on PostGIS and builds the APK and the images. Once a server exists
and the repository variable `DEPLOY_ENABLED=true` is set, `main` deploys to staging (then runs
`jamii e2e`) and version tags deploy to production after approval.

## Where to start reading

1. `docs/decisions/0001-open-decisions-and-defaults.md`: what was assumed, and what to settle with the county.
2. `api/tests/test_loop.py`: the whole loop in one test.
3. `docs/compliance-checklist.md`: what is built and what still needs people and paperwork.
