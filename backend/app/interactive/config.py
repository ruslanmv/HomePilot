"""
Runtime settings for the interactive service.

All values read from env at ``load_config()`` time (not import time)
so tests and live reloads pick up overrides without restart churn.

Design rule: every flag has a safe default such that an unconfigured
install behaves identically to the pre-interactive codebase. Turning
``INTERACTIVE_ENABLED=false`` (the default) must keep the router
empty, the schema un-applied, and zero background work running.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key, "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, "").strip() or default)
    except (TypeError, ValueError):
        return default


def _env_str(key: str, default: str) -> str:
    raw = os.getenv(key, "")
    return raw.strip() if raw.strip() else default


def _env_list(key: str, default: Optional[List[str]] = None) -> List[str]:
    """Comma-separated list env var. Empty → default."""
    raw = os.getenv(key, "").strip()
    if not raw:
        return list(default or [])
    return [p.strip() for p in raw.split(",") if p.strip()]


@dataclass(frozen=True)
class InteractiveConfig:
    """Resolved runtime settings. Immutable after ``load_config``.

    The ``enabled`` flag is the master switch. When false the router
    returned by ``build_router()`` has no routes — the service
    contributes zero paths to the OpenAPI schema. Nothing else in
    this package should ever be executed.
    """

    # Master switch. All other settings are irrelevant when False.
    enabled: bool = False

    # Structural safety caps on the branching graph. Planner refuses
    # to emit graphs beyond these bounds; prevents exponential blowup.
    max_branches: int = 12
    max_depth: int = 6
    max_nodes_per_experience: int = 200

    # LLM model id used by the planner / script generator. Falls
    # through to HomePilot's default Ollama model when unset.
    llm_model: str = "llama3:8b"

    # Where generated interactive artifacts live on disk. Empty
    # string → reuse UPLOAD_DIR (standard HomePilot storage).
    storage_root: str = ""

    # Default-on chassis guardrails for mature-mode experiences.
    # These cannot be disabled per-profile; they're the permanent
    # safety net. Setting any to False requires editing source code.
    require_consent_for_mature: bool = True
    enforce_region_block: bool = True
    moderate_mature_narration: bool = True

    # Regions hard-blocked for mature content (ISO 3166-1 alpha-2
    # codes). Checked BEFORE any profile-level rule. Empty → no
    # blocks; admins configure via INTERACTIVE_REGION_BLOCK env.
    region_block: List[str] = field(default_factory=list)

    # p50 latency target for the runtime loop excluding asset
    # generation. Not enforced — used by QA assertions only.
    runtime_latency_target_ms: int = 200


def load_config() -> InteractiveConfig:
    """Resolve a fresh config from the current environment.

    Called once at mount (see ``main.py``) and by tests that need a
    per-test override via monkeypatch.
    """
    return InteractiveConfig(
        enabled=_env_bool("INTERACTIVE_ENABLED", False),
        max_branches=_env_int("INTERACTIVE_MAX_BRANCHES", 12),
        max_depth=_env_int("INTERACTIVE_MAX_DEPTH", 6),
        max_nodes_per_experience=_env_int("INTERACTIVE_MAX_NODES", 200),
        llm_model=_env_str("INTERACTIVE_LLM_MODEL", "llama3:8b"),
        storage_root=_env_str("INTERACTIVE_STORAGE_ROOT", ""),
        require_consent_for_mature=_env_bool("INTERACTIVE_REQUIRE_MATURE_CONSENT", True),
        enforce_region_block=_env_bool("INTERACTIVE_ENFORCE_REGION_BLOCK", True),
        moderate_mature_narration=_env_bool("INTERACTIVE_MODERATE_MATURE", True),
        region_block=_env_list("INTERACTIVE_REGION_BLOCK", default=[]),
        runtime_latency_target_ms=_env_int("INTERACTIVE_LATENCY_TARGET_MS", 200),
    )
