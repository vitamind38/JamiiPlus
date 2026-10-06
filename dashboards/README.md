# Dashboards

Two kinds, for two jobs.

**In the officer web app (`/`)**: scoped to the logged-in person's level. A CHA sees their
unit's ward, a sub-county officer their sub-county, and so on. Reports by theme, week and
ward; issues by status; median days from report to first response; share of issues with a
recorded action; review queue size; model agreement. Code: `api/src/jamii_api/services/stats.py`.

**Metabase (`docker compose --profile dashboards up -d`)**: for county and national analysts
building their own charts. It connects as `metabase_reader`, which can read only the
`dashboards` schema: de-identified views with no CHP ids and no report text.

| View | One row per | Use |
|---|---|---|
| `dashboards.reports` | report | Counts by theme, place, channel, week; human-reviewed vs model-accepted |
| `dashboards.issues` | issue | Status, level, days to first response, whether action was recorded |
| `dashboards.report_response_times` | report | The pilot's main outcome: days from report to first response |
| `dashboards.weekly_theme_counts` | week × place × theme | Trends and the basis for spike checks |
| `dashboards.response_summary` | sub-county | Median response time and share of issues with action |
| `dashboards.review_queue` | queue × sub-county | Backlog and the oldest waiting report |
| `dashboards.model_agreement_weekly` | week × model version | Reviewer agreement, published every week |
| `dashboards.unit_map` | community health unit | Latitude/longitude of the unit's point and recent report count, for maps |

The views are created by `api/alembic/versions/0002_dashboard_views.py`. Charts must read the
views, never the tables, so a table can change without breaking a chart; when a table
changes, a new migration updates the view.

## Setting up Metabase

1. Open `https://$METABASE_DOMAIN`, create the admin account (a named person).
2. Add database: PostgreSQL, host `postgres`, database `jamii`, user `metabase_reader`,
   password `METABASE_READER_PASSWORD` from `infra/.env`. Schema filter: `dashboards`.
3. Turn off "Allow downloads" for groups that do not need raw rows.
4. Export finished dashboards (Metabase serialization or screenshots of the question SQL) into
   this folder so they can be rebuilt.
