#!/usr/bin/env bash
set -e

export AVATAR_SERVICE_PORT="${AVATAR_SERVICE_PORT:-8020}"

echo "Starting HomePilot Avatar Service on port $AVATAR_SERVICE_PORT..."
uvicorn app.main:app --host 0.0.0.0 --port "$AVATAR_SERVICE_PORT" --reload
