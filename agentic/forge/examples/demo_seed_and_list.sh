#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${MCPGATEWAY_URL:-http://localhost:4444}"
USER="${BASIC_AUTH_USER:-admin}"
PASS="${BASIC_AUTH_PASSWORD:-changeme}"

python agentic/forge/seed/seed_all.py

echo ""
echo "Tools:"
curl -s -u "${USER}:${PASS}" "${BASE_URL}/tools" | jq '.[] | {name, description}'

echo ""
echo "A2A Agents:"
curl -s -u "${USER}:${PASS}" "${BASE_URL}/a2a" | jq '.[] | {name, description}'

echo ""
echo "Virtual Servers:"
curl -s -u "${USER}:${PASS}" "${BASE_URL}/servers" | jq '.[] | {name, description}'
