#!/usr/bin/env bash
# Run every test and lint locally with one command:  scripts/check.sh
# Uses SQLite for the API tests; CI repeats them on PostGIS. Set TEST_DATABASE_URL to use Postgres.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=python
[ -x .venv/bin/python ] && PY=.venv/bin/python
[ -x .venv/Scripts/python.exe ] && PY=.venv/Scripts/python.exe

echo "== guard: personal data and secrets"
$PY scripts/check_no_personal_data.py

echo "== lint"
$PY -m ruff check .
$PY -m ruff format --check api/src api/tests workers ml scripts

echo "== api"
(cd api && "../$PY" -m pytest -q -p no:warnings)
echo "== workers"
(cd workers && "../$PY" -m pytest -q -p no:warnings)
echo "== model service and ML scripts"
(cd ml/service && "../../$PY" -m pytest -q -p no:warnings)

if command -v flutter >/dev/null 2>&1 && [ -d mobile ]; then
  echo "== mobile"
  (cd mobile && flutter analyze && flutter test)
fi
echo "All checks passed."
