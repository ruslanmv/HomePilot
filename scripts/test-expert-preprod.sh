#!/usr/bin/env bash
set -euo pipefail

PORT="${PREPROD_BACKEND_PORT:-18000}"
BASE="http://localhost:${PORT}"

echo "Checking Expert preprod at ${BASE}"

INFO_JSON="$(curl -fsS "${BASE}/v1/expert/info")"
python3 - <<'PY' "$INFO_JSON"
import json,sys
j=json.loads(sys.argv[1])
assert "available_providers" in j, "missing available_providers"
assert "default_provider" in j, "missing default_provider"
print("✓ /v1/expert/info contract OK")
PY

CHAT_JSON="$(curl -fsS -X POST "${BASE}/v1/expert/chat" -H 'content-type: application/json' -d '{"query":"Give me a short answer about local-first AI architecture.","thinking_mode":"auto","provider":"auto","feature_hints":{"budgetTier":"low"}}')"
python3 - <<'PY' "$CHAT_JSON"
import json,sys
j=json.loads(sys.argv[1])
required=["content","provider_used","thinking_mode_used","strategy_used","fallback_applied","notices","latency_ms"]
for k in required:
    assert k in j, f"missing {k}"
assert isinstance(j["notices"], list), "notices must be list"
print("✓ /v1/expert/chat metadata contract OK")
PY

echo "✅ Expert preprod smoke test passed"
