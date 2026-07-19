#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "Missing digitalocean/.env. Copy .env.example and fill in the required values." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

: "${HOMEPILOT_DOMAIN:?HOMEPILOT_DOMAIN is required}"
: "${ACME_EMAIL:?ACME_EMAIL is required}"
: "${API_KEY:?API_KEY is required}"

if [[ ${#API_KEY} -lt 32 || "$API_KEY" == replace-* ]]; then
  echo "API_KEY must be a strong random value of at least 32 characters." >&2
  exit 1
fi

docker compose pull
docker compose up -d --remove-orphans
docker compose ps

echo "HomePilot deployment requested for https://${HOMEPILOT_DOMAIN}"
