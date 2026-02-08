#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${MCPGATEWAY_URL:-http://localhost:4444}"
AUTH_USER="${BASIC_AUTH_USER:-admin}"
AUTH_PASS="${BASIC_AUTH_PASSWORD:-changeme}"

echo "Seeding placeholder tool + A2A agent into Forge at $BASE_URL"

curl -s -X POST "$BASE_URL/tools" -u "$AUTH_USER:$AUTH_PASS" \
  -H "Content-Type: application/json" \
  -d '{
    "tool": {
      "name": "placeholder_echo",
      "description": "Placeholder MCP tool: echoes input. Replace with real tool.",
      "inputSchema": {
        "type": "object",
        "properties": { "text": { "type": "string" } },
        "required": ["text"]
      }
    }
  }' >/dev/null || true

curl -s -X POST "$BASE_URL/a2a" -u "$AUTH_USER:$AUTH_PASS" \
  -H "Content-Type: application/json" \
  -d '{
    "agent": {
      "name": "placeholder_agent",
      "description": "Placeholder A2A agent for wiring UI. Replace later.",
      "endpoint_url": "http://localhost:9100/a2a",
      "agent_type": "generic",
      "protocol_version": "1.0"
    },
    "visibility": "public"
  }' >/dev/null || true

echo "Done."
