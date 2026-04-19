"""
Chassis-level safety guardrails.

These three rules are enforced BEFORE any profile-level decision
runs. They cannot be disabled by editing a profile YAML — a
misconfigured profile that allows mature content without consent
will still be blocked here.

Guardrails:

  G1. Mature content requires explicit session consent.
      The experience's mode is mature_gated (or the profile has
      mature_consent_required=True) AND the session.consent_version
      is empty → block with reason_code='consent_required'.

  G2. Region block.
      If the config's ``region_block`` list contains the viewer's
      detected region → block with reason_code='region_blocked'.

  G3. Terminal moderation.
      Before asset generation for mature-mode narration, run a
      moderation check. Failure → block with
      reason_code='narration_moderation_failed'. This catches the
      case where the LLM generates something the policy profile
      forgot to enumerate.

All three have per-guardrail config flags (see ``config.py``) but
**only to allow operators to tighten beyond the default** — the
flags default to ON and turning them OFF requires editing source
(the env vars are intentionally documented as "must be false in
backend/.env" rather than a UI toggle).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..config import InteractiveConfig


@dataclass(frozen=True)
class ChassisResult:
    """Outcome of applying all three chassis guardrails."""

    allowed: bool
    reason_code: str = ""   # empty when allowed=True
    message: str = ""       # human-readable, not leaked to viewer by default
    guardrail_id: str = ""  # 'G1' | 'G2' | 'G3'


_ALLOW = ChassisResult(allowed=True)


def _check_consent(
    cfg: InteractiveConfig,
    mode: str,
    mature_required: bool,
    consent_version: str,
) -> Optional[ChassisResult]:
    """G1 — mature content requires explicit session consent."""
    if not cfg.require_consent_for_mature:
        return None
    if mode == "mature_gated" or mature_required:
        if not consent_version or not consent_version.strip():
            return ChassisResult(
                allowed=False,
                reason_code="consent_required",
                message="Mature content requires explicit session consent.",
                guardrail_id="G1",
            )
    return None


def _check_region(cfg: InteractiveConfig, viewer_region: str) -> Optional[ChassisResult]:
    """G2 — reject viewers from blocked regions."""
    if not cfg.enforce_region_block:
        return None
    if not viewer_region:
        return None
    rr = viewer_region.strip().upper()
    if rr and rr in {r.upper() for r in cfg.region_block}:
        return ChassisResult(
            allowed=False,
            reason_code="region_blocked",
            message=f"Viewer region '{rr}' is in the global block list.",
            guardrail_id="G2",
        )
    return None


def _check_narration_moderation(
    cfg: InteractiveConfig, mode: str, moderation_flags: List[str],
) -> Optional[ChassisResult]:
    """G3 — fail generation on moderation flags for mature mode."""
    if not cfg.moderate_mature_narration:
        return None
    if mode != "mature_gated":
        return None
    if moderation_flags:
        return ChassisResult(
            allowed=False,
            reason_code="narration_moderation_failed",
            message=f"Narration flagged by moderation: {', '.join(moderation_flags)}",
            guardrail_id="G3",
        )
    return None


def apply_chassis_guardrails(
    cfg: InteractiveConfig,
    *,
    experience_mode: str,
    mature_consent_required: bool = False,
    session_consent_version: str = "",
    viewer_region: str = "",
    narration_moderation_flags: Optional[List[str]] = None,
) -> ChassisResult:
    """Run the three chassis guardrails. First failure wins.

    Called from three places at runtime:
      - session start          → G1 + G2 apply
      - action execution       → G1 applies (consent could be revoked mid-session)
      - pre-generation (mature)→ G3 applies after the LLM returns narration

    When none of the guardrails trigger, returns the shared
    ``_ALLOW`` instance (cheap hot path).
    """
    flags = list(narration_moderation_flags or [])
    for check in (
        _check_consent(cfg, experience_mode, mature_consent_required, session_consent_version),
        _check_region(cfg, viewer_region),
        _check_narration_moderation(cfg, experience_mode, flags),
    ):
        if check is not None:
            return check
    return _ALLOW
