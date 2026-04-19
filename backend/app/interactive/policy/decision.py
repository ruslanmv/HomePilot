"""
Decision engine — the three explicit checkpoints the router calls.

The runtime loop consults the decision engine three times:

  check_catalog_visibility(action, experience, session)
    → Should this action appear in the ``actions[]`` array returned
      to the viewer's right-panel? Answer: Decision.
    Reasons: catalog_mode_not_applicable, level_gate, consent_required,
             policy_blocked.

  check_action_execution(action, experience, session, state)
    → The viewer clicked a visible action; is it still OK to fire?
      (Consent / region could've changed mid-session, cooldown
      might not have elapsed, etc.)
    Reasons: cooldown, policy_blocked, consent_required, region_blocked.

  check_free_input(text, experience, session, state)
    → The viewer typed free text. Classify, then decide whether to
      allow / soft-refuse / block.
    Reasons: policy_blocked, soft_refuse, unknown_intent.

All three return the same ``Decision`` shape so the router layer
has one response pattern.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..config import InteractiveConfig
from ..models import Action, Experience, Session
from .classifier import IntentMatch, classify_intent
from .guardrails import apply_chassis_guardrails
from .profiles import PolicyProfile, load_profile


# Decision outcomes. Keep the set small and stable so the frontend
# can switch-case on them.
DECISION_ALLOW = "allow"
DECISION_SOFT_REFUSE = "soft_refuse"
DECISION_BLOCK = "block"


@dataclass(frozen=True)
class Decision:
    """Result of a decision check.

    ``decision`` is one of the three outcome strings above.
    ``reason_code`` is a stable short identifier (e.g. 'level_gate')
    the frontend can inspect. ``message`` is the template copy
    (already localized by the caller when appropriate).
    """

    decision: str
    reason_code: str = "ok"
    message: str = ""
    intent_code: str = ""
    extra: Dict[str, Any] = None  # type: ignore[assignment]

    def is_allow(self) -> bool:
        return self.decision == DECISION_ALLOW


_ALLOW = Decision(decision=DECISION_ALLOW, reason_code="ok", extra={})


# Intents that are ALWAYS blocked regardless of which profile is
# active. These are chassis-level safety rules — no profile YAML
# can enable them. Edit only in source code.
_UNIVERSAL_BLOCK_INTENTS = frozenset({
    "minor_reference",
    "violence_request",
    "non_consent_scenario",
})


def _decision_block(reason: str, msg: str = "", intent: str = "") -> Decision:
    return Decision(decision=DECISION_BLOCK, reason_code=reason, message=msg, intent_code=intent, extra={})


def _decision_soft_refuse(profile: PolicyProfile, intent: str) -> Decision:
    return Decision(
        decision=DECISION_SOFT_REFUSE,
        reason_code="soft_refuse",
        message=profile.soft_refuse_template or "Let's redirect — different angle?",
        intent_code=intent,
        extra={"profile_id": profile.id},
    )


def _resolve_profile(experience: Experience) -> PolicyProfile:
    """Find the profile for an experience. Falls back to sfw_general
    if the configured profile is missing."""
    prof = load_profile(experience.policy_profile_id)
    if prof is None:
        prof = load_profile("sfw_general")
    # Guaranteed by profiles._BUILTIN_PROFILES seeding; narrow for mypy.
    assert prof is not None
    return prof


# ─────────────────────────────────────────────────────────────────
# Check 1 — catalog visibility
# ─────────────────────────────────────────────────────────────────

def check_catalog_visibility(
    cfg: InteractiveConfig,
    action: Action,
    experience: Experience,
    session: Optional[Session] = None,
    *,
    viewer_region: str = "",
) -> Decision:
    """Decide whether ``action`` should appear (possibly locked) in
    the viewer's action panel. Visibility != execution permission —
    locked items are still visible so the viewer can see they exist.
    """
    # Mode filter — action.applicable_modes is a list; empty = applies everywhere.
    if action.applicable_modes and experience.experience_mode not in action.applicable_modes:
        return _decision_block("mode_not_applicable", "Action not available in this mode.")

    profile = _resolve_profile(experience)

    # Chassis — region block is a visibility-level check (viewer
    # in blocked region shouldn't even see mature catalog).
    consent_version = session.consent_version if session else ""
    chassis = apply_chassis_guardrails(
        cfg,
        experience_mode=experience.experience_mode,
        mature_consent_required=profile.mature_consent_required,
        session_consent_version=consent_version,
        viewer_region=viewer_region,
    )
    if not chassis.allowed and chassis.reason_code == "region_blocked":
        return _decision_block(chassis.reason_code, chassis.message)

    # Universal-block intents — no profile can surface them.
    if action.intent_code and action.intent_code in _UNIVERSAL_BLOCK_INTENTS:
        return _decision_block(
            "policy_blocked",
            f"Intent '{action.intent_code}' is universally blocked.",
        )

    # Intent-level whitelist/blacklist.
    if action.intent_code and profile.blocks_intent(action.intent_code):
        return _decision_block("policy_blocked", f"Intent '{action.intent_code}' is blocked in this profile.")

    # An action's requires_consent is an ADDITIONAL gate beyond the
    # chassis — e.g. a specific action in social_romantic mode that
    # needs age confirmation despite the mode itself not being
    # mature.
    if action.requires_consent and (not session or not session.consent_version):
        return _decision_block("consent_required", f"Action requires '{action.requires_consent}' consent.")

    return _ALLOW


# ─────────────────────────────────────────────────────────────────
# Check 2 — action execution
# ─────────────────────────────────────────────────────────────────

def check_action_execution(
    cfg: InteractiveConfig,
    action: Action,
    experience: Experience,
    session: Session,
    *,
    viewer_region: str = "",
    last_used_at_ms: int = 0,
    uses_this_session: int = 0,
    now_ms: int = 0,
) -> Decision:
    """The viewer clicked a visible action. Check for cooldown,
    per-session cap, and re-verify chassis / profile gates."""
    # Re-apply chassis (consent can be revoked, region can change
    # if the viewer is on mobile and switched networks).
    profile = _resolve_profile(experience)
    chassis = apply_chassis_guardrails(
        cfg,
        experience_mode=experience.experience_mode,
        mature_consent_required=profile.mature_consent_required,
        session_consent_version=session.consent_version,
        viewer_region=viewer_region,
    )
    if not chassis.allowed:
        return _decision_block(chassis.reason_code, chassis.message)

    # Universal-block re-check (defense in depth — profile could
    # have been hot-reloaded to something permissive).
    if action.intent_code and action.intent_code in _UNIVERSAL_BLOCK_INTENTS:
        return _decision_block(
            "policy_blocked",
            f"Intent '{action.intent_code}' is universally blocked.",
        )

    # Policy profile re-check.
    if action.intent_code and profile.blocks_intent(action.intent_code):
        return _decision_block("policy_blocked", f"Intent '{action.intent_code}' blocked.")

    # Cooldown.
    if action.cooldown_sec and last_used_at_ms and now_ms:
        elapsed_s = (now_ms - last_used_at_ms) / 1000.0
        if elapsed_s < float(action.cooldown_sec):
            remaining = float(action.cooldown_sec) - elapsed_s
            return Decision(
                decision=DECISION_BLOCK,
                reason_code="cooldown",
                message=f"Cooldown: wait {remaining:.1f}s.",
                intent_code=action.intent_code,
                extra={"remaining_sec": remaining},
            )

    # Per-session cap.
    if action.max_uses_per_session and uses_this_session >= action.max_uses_per_session:
        return _decision_block(
            "max_uses_exceeded",
            f"Max uses ({action.max_uses_per_session}) for this session reached.",
        )

    return _ALLOW


# ─────────────────────────────────────────────────────────────────
# Check 3 — free-text input
# ─────────────────────────────────────────────────────────────────

def check_free_input(
    cfg: InteractiveConfig,
    text: str,
    experience: Experience,
    session: Session,
    *,
    viewer_region: str = "",
) -> Decision:
    """Classify free text then decide allow / soft_refuse / block."""
    profile = _resolve_profile(experience)
    match: IntentMatch = classify_intent(text)

    # Chassis first — region block applies regardless of intent.
    chassis = apply_chassis_guardrails(
        cfg,
        experience_mode=experience.experience_mode,
        mature_consent_required=profile.mature_consent_required,
        session_consent_version=session.consent_version,
        viewer_region=viewer_region,
    )
    if not chassis.allowed:
        return Decision(
            decision=DECISION_BLOCK,
            reason_code=chassis.reason_code,
            message=chassis.message,
            intent_code=match.intent_code,
            extra={"guardrail_id": chassis.guardrail_id},
        )

    # Universal safety intents — always hard-blocked, no matter the
    # profile. Cannot be unlocked via YAML.
    if match.intent_code in _UNIVERSAL_BLOCK_INTENTS:
        return _decision_block(
            "policy_blocked",
            f"Intent '{match.intent_code}' is universally blocked.",
            intent=match.intent_code,
        )

    # Profile-specific hard-block intents.
    if profile.blocks_intent(match.intent_code):
        return _decision_block(
            "policy_blocked",
            f"Intent '{match.intent_code}' blocked in profile '{profile.id}'.",
            intent=match.intent_code,
        )

    # Allow-list — if the profile has one and our intent isn't in
    # it, soft-refuse instead of hard-block. This is the "let's
    # stay on topic" redirect behavior for teaching mode.
    if profile.allowed_intents and match.intent_code not in profile.allowed_intents:
        # Unknown / empty gets soft-refused too (the viewer typed
        # nothing relevant).
        return _decision_soft_refuse(profile, match.intent_code)

    return Decision(
        decision=DECISION_ALLOW,
        reason_code="ok",
        intent_code=match.intent_code,
        extra={"confidence": match.confidence, "pattern": match.matched_pattern},
    )
