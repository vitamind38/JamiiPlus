#!/usr/bin/env bash
# Deploy a release on the server, or roll back to the previous one.
#
#   infra/scripts/deploy.sh v0.3.0        # deploy a tagged release
#   infra/scripts/deploy.sh --rollback    # go back to the previous release
#
# Images are built by CI and tagged with the release; old images are kept so a rollback is
# just a restart on the previous tag. Migrations must stay backwards compatible for one
# release, so rolling the code back does not need a database downgrade.
set -euo pipefail

cd "$(dirname "$0")/.."
STATE=/var/lib/jamii/releases
mkdir -p "$STATE"
current="$(cat "$STATE/current" 2>/dev/null || echo "")"

if [ "${1:-}" = "--rollback" ]; then
  target="$(cat "$STATE/previous" 2>/dev/null || true)"
  [ -n "$target" ] || { echo "No previous release recorded." >&2; exit 1; }
else
  target="${1:?release tag, e.g. v0.3.0}"
fi

export JAMII_VERSION="$target"
echo "Deploying $target (current: ${current:-none})"
docker compose pull api worker beat model migrate 2>/dev/null || docker compose build
docker compose run --rm migrate
docker compose up -d --remove-orphans

for _ in $(seq 1 30); do
  if docker compose exec -T api python -c \
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3)" 2>/dev/null; then
    [ "$target" != "$current" ] && { echo "$current" > "$STATE/previous"; echo "$target" > "$STATE/current"; }
    echo "Healthy on $target"
    exit 0
  fi
  sleep 2
done
echo "API did not become ready on $target. Run: infra/scripts/deploy.sh --rollback" >&2
exit 1
