#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "Missing oracle/.env. Copy .env.example and fill in the required values." >&2
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

# ── Disk space before the pull ───────────────────────────────────────────────
# The 2026-10-26 deploy died mid-pull with "no space left on device" while
# extracting the app image (its ComfyUI venv alone is several GB). Cause: every
# deploy tags its image with the commit id (homepilot-oracle:<sha>), and the old
# cleanup ran `docker image prune -f` *after* the pull, which removes only
# untagged images. Each previous :<sha> image stayed tagged, so one full image
# copy piled up per deploy until the boot volume was full.
#
# So: clear what nothing uses *before* pulling. `image prune -a` keeps every
# image a container (running or stopped) still uses, so the live site's image
# and Caddy's stay; old :<sha> images, stopped containers and build cache go.
# Volumes are never touched — they hold the app's data and Caddy's certificates.
# Free GB on the filesystem holding Docker's data (and containerd's snapshots,
# where the failed extraction was writing); "/" when Docker cannot say.
DOCKER_ROOT="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || true)"
[[ -d "${DOCKER_ROOT:-}" ]] || DOCKER_ROOT=/
free_gb() { df -P -BG "$DOCKER_ROOT" 2>/dev/null | awk 'NR==2 { gsub("G", "", $4); print $4 }'; }

echo "Disk before cleanup: $(free_gb) GB free on ${DOCKER_ROOT}"
docker container prune -f >/dev/null 2>&1 || true
docker image prune -af >/dev/null 2>&1 || true
docker builder prune -af >/dev/null 2>&1 || true
echo "Disk after cleanup:  $(free_gb) GB free"

# The new image is pulled while the old one is still running, so both must fit.
# Stop here with a readable report rather than fail halfway through extraction;
# the site keeps running on its current image. Raise or lower with MIN_FREE_GB.
MIN_FREE_GB="${MIN_FREE_GB:-8}"
avail="$(free_gb)"
if [[ -n "$avail" && "$avail" -lt "$MIN_FREE_GB" ]]; then
  echo "Not enough disk to pull the new image: ${avail} GB free, need ${MIN_FREE_GB} GB." >&2
  echo "The running site was left as it is. What is using the disk:" >&2
  df -h "$DOCKER_ROOT" >&2 || true
  docker system df >&2 || true
  echo "Grow the boot volume (Always Free allows up to 200 GB in total), or free space, then redeploy." >&2
  exit 1
fi

docker compose pull
docker compose up -d --remove-orphans
docker compose ps

# The stack now runs the new image, so the previous one is unused: remove it too
# (not only untagged layers), leaving the disk ready for the next deploy.
docker image prune -af >/dev/null 2>&1 || true
echo "Disk after deploy:   $(free_gb) GB free"

echo "HomePilot deployment requested for https://${HOMEPILOT_DOMAIN}"
