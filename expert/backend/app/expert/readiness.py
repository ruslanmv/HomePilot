from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List


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
