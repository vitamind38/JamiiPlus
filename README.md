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
