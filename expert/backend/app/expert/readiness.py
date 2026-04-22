from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List

from .mcp_catalog import mcp_key_to_env, p0_required_server_keys


@dataclass
class ReadinessCheck:
    name: str
    passed: bool
    detail: str


@dataclass
class ReadinessReport:
    ready: bool
    stage: str
    checks: List[ReadinessCheck]


def build_readiness_report(env: Dict[str, str] | None = None) -> ReadinessReport:
    source = env or dict(os.environ)
    preprod_mode = _truthy(source.get("EXPERT_PREPROD_MODE"))

    checks = [
        _check("tools_live", _truthy(source.get("EXPERT_TOOLS_ENABLED")), "Tool layer must be enabled."),
        _check("memory_enabled", _truthy(source.get("EXPERT_MEMORY_ENABLED")), "Memory layer must be enabled."),
        _check("evals_enabled", _truthy(source.get("EXPERT_EVALS_ENABLED")), "Eval recording must be enabled."),
        _check("router_v2", _truthy(source.get("EXPERT_V2_ROUTER_ENABLED")), "V2 router must be enabled."),
        _check(
            "persistent_memory",
            bool(source.get("EXPERT_MEMORY_BACKEND", "").strip()),
            "Persistent memory backend must be configured.",
        ),
        _check(
            "observability",
            bool(source.get("EXPERT_TELEMETRY_ENDPOINT", "").strip()),
            "Telemetry endpoint must be configured.",
        ),
        _check(
            "safety_policy",
            bool(source.get("EXPERT_SAFETY_POLICY", "").strip()),
            "Safety policy profile must be configured.",
        ),
    ]
    checks.extend(_mcp_preprod_checks(source, enabled=preprod_mode))

    passed = sum(1 for c in checks if c.passed)
    ready = passed == len(checks)
    if ready:
        stage = "production"
    elif passed >= 4:
        stage = "preprod"
    else:
        stage = "dev"

    return ReadinessReport(ready=ready, stage=stage, checks=checks)


def _check(name: str, passed: bool, detail: str) -> ReadinessCheck:
    return ReadinessCheck(name=name, passed=passed, detail=detail)


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "on"}


def _mcp_preprod_checks(source: Dict[str, str], enabled: bool) -> List[ReadinessCheck]:
    checks: List[ReadinessCheck] = []
    if not enabled:
        return checks
    orchestrator = (source.get("EXPERT_MCP_ORCHESTRATOR", "context_forge") or "context_forge").strip().lower()
    checks.append(
        _check(
            "mcp_orchestrator",
            orchestrator in {"context_forge", "direct"},
            "EXPERT_MCP_ORCHESTRATOR must be 'context_forge' or 'direct'.",
        )
    )

    if orchestrator == "context_forge":
        checks.append(
            _check(
                "context_forge_url",
                bool(source.get("CONTEXT_FORGE_URL", "").strip()),
                "Set CONTEXT_FORGE_URL for MCP Context Forge orchestration.",
            )
        )
        return checks

    for key in p0_required_server_keys():
        env_key = mcp_key_to_env(key)
        checks.append(
            _check(
                f"mcp:{key}",
                bool(source.get(env_key, "").strip()),
                f"Set {env_key} for preprod MCP P0 integration.",
            )
        )
    return checks
