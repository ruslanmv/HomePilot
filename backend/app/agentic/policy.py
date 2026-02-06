"""Policy layer — allowlist, defaults profiles, and safety guardrails.

Every invocation passes through here before reaching Context Forge so we can
enforce rate-limit-like constraints and map "profile" tags to concrete
generation parameters.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("homepilot.agentic.policy")

# ── Defaults profiles ─────────────────────────────────────────────────────────
# The frontend sends profile="fast"|"balanced"|"quality".
# We translate that to parameter overrides understood by the downstream tool.

PROFILES: Dict[str, Dict[str, Any]] = {
    "fast": {
        "max_tokens": 512,
        # Image: use the model-config preset system (low/med/high) instead of
        # hard-coded dimensions — this respects SDXL bucketed training resolutions
        # and model-specific steps/CFG (Pony V6, Flux, SD1.5, etc.).
        "img_preset": "low",
        "vid_frames": 25,
        "vid_steps": 20,
        "vid_cfg": 3.5,
    },
    "balanced": {
        "max_tokens": 1024,
        "img_preset": "med",
        "vid_frames": 33,
        "vid_steps": 24,
        "vid_cfg": 4.0,
    },
    "quality": {
        "max_tokens": 2048,
        "img_preset": "high",
        "vid_frames": 49,
        "vid_steps": 32,
        "vid_cfg": 4.0,
    },
}

# ── Capability allowlist ──────────────────────────────────────────────────────
# Only capabilities listed here can be invoked through the /invoke endpoint.
# This is the single security gate for the agentic layer.

ALLOWED_CAPABILITIES = frozenset(
    {
        "generate_images",
        "generate_videos",
        "code_analysis",
        "data_analysis",
        "web_search",
        "document_qa",
        "story_generation",
        "agent_chat",
    }
)


def resolve_profile(profile: str) -> Dict[str, Any]:
    """Return the parameter overrides for the given profile name."""
    return PROFILES.get(profile, PROFILES["fast"]).copy()


def is_allowed(capability_id: str) -> bool:
    """Return True if the capability id is on the allow-list."""
    return capability_id in ALLOWED_CAPABILITIES


def apply_policy(intent: str, args: Dict[str, Any], profile: str) -> Dict[str, Any]:
    """Merge profile defaults into *args* (user-supplied values win)."""
    if not is_allowed(intent):
        raise PermissionError(f"Capability '{intent}' is not in the allow-list")

    merged = resolve_profile(profile)
    merged.update(args)  # caller overrides win
    logger.debug("policy: intent=%s profile=%s → %s", intent, profile, merged)
    return merged
