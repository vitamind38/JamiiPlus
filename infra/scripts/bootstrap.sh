#!/usr/bin/env bash
# First start on a new server: load the theme list and create the first admin.
#
#   infra/scripts/bootstrap.sh 0712345678 "Full Name"
set -euo pipefail

cd "$(dirname "$0")/.."
PHONE="${1:?admin phone number}"
NAME="${2:?admin full name}"
docker compose run --rm migrate
docker compose run --rm api jamii seed-themes
docker compose run --rm api jamii create-admin --phone "$PHONE" --name "$NAME"
echo "Log in at https://${JAMII_DOMAIN:-<your domain>}/login and register units, officers and CHPs under Admin."
