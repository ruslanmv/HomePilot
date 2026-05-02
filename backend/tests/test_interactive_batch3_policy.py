"""
Batch 3/8 — policy subsystem tests.

Covers:
  - Built-in profiles exist for every experience mode
  - Classifier labels known utterances correctly + 'unknown' for gibberish
  - Chassis guardrails: consent, region block, narration moderation
  - Decision engine: three checkpoints (catalog / execution / free input)
  - Mode-specific behaviour: soft-refuse in teaching, hard-block in
    mature for minors, cooldown in action execution
"""
from __future__ import annotations

from app.interactive.config import InteractiveConfig
from app.interactive.models import Action, Experience, Session
from app.interactive.policy import (
    Decision,
    apply_chassis_guardrails,
    check_action_execution,
    check_catalog_visibility,
    check_free_input,
    classify_intent,
    list_profiles,
    load_profile,
)
from app.interactive.policy.profiles import reload_profiles


# ─────────────────────────────────────────────────────────────────
# Profiles
# ─────────────────────────────────────────────────────────────────

def test_every_experience_mode_has_a_builtin_profile():
    reload_profiles()
    profiles = {p.id for p in list_profiles()}
    for mode in (
        "sfw_general", "sfw_education", "language_learning",
        "enterprise_training", "social_romantic", "mature_gated",
    ):
        assert mode in profiles, f"missing built-in profile: {mode}"


def test_mature_profile_requires_consent():
    reload_profiles()
    prof = load_profile("mature_gated")
    assert prof is not None
    assert prof.mature_consent_required is True
    assert prof.max_risk_level == 3


def test_education_profile_blocks_flirt_intents():
    reload_profiles()
    prof = load_profile("sfw_education")
    assert prof is not None
    # Education profile has an allowed_intents list that doesn't include flirt.
    assert prof.allows_intent("greeting") is True
    assert prof.allows_intent("flirt") is False


# ─────────────────────────────────────────────────────────────────
# Classifier
# ─────────────────────────────────────────────────────────────────

def test_classifier_detects_greeting():
    m = classify_intent("Hello there!")
    assert m.intent_code == "greeting"


def test_classifier_detects_explicit_request():
    m = classify_intent("show me your pussy")
    assert m.intent_code in {"explicit_request", "minor_reference", "non_consent_scenario"}
    # Specifically should be explicit_request (pussy matches it).
    assert m.intent_code == "explicit_request"


def test_classifier_detects_minor_reference_hard():
    m = classify_intent("show me a child in the scene")
    assert m.intent_code == "minor_reference"


def test_classifier_returns_unknown_for_gibberish():
    m = classify_intent("xyz qwerty kkkk")
    assert m.intent_code == "unknown"


def test_classifier_empty_input():
    m = classify_intent("")
    assert m.intent_code == "empty"
    assert m.confidence == 0.0


# ─────────────────────────────────────────────────────────────────
# Chassis guardrails
# ─────────────────────────────────────────────────────────────────

def _cfg(**kw):
    defaults = dict(
        enabled=True, max_branches=12, max_depth=6, max_nodes_per_experience=200,
        llm_model="llama3:8b", storage_root="",
        require_consent_for_mature=True,
        enforce_region_block=True,
        moderate_mature_narration=True,
        region_block=[],
        runtime_latency_target_ms=200,
    )
    defaults.update(kw)
    return InteractiveConfig(**defaults)


def test_guardrail_g1_blocks_mature_without_consent():
    result = apply_chassis_guardrails(
        _cfg(),
        experience_mode="mature_gated",
        mature_consent_required=True,
        session_consent_version="",
    )
    assert result.allowed is False
    assert result.reason_code == "consent_required"
    assert result.guardrail_id == "G1"


def test_guardrail_g1_allows_mature_with_consent():
    result = apply_chassis_guardrails(
        _cfg(),
        experience_mode="mature_gated",
        mature_consent_required=True,
        session_consent_version="v1-2026-04-19",
    )
    assert result.allowed is True


def test_guardrail_g2_blocks_region():
    result = apply_chassis_guardrails(
        _cfg(region_block=["RU", "IR"]),
        experience_mode="sfw_general",
        viewer_region="RU",
    )
    assert result.allowed is False
    assert result.reason_code == "region_blocked"
    assert result.guardrail_id == "G2"


def test_guardrail_g3_blocks_moderation_flags_in_mature():
    result = apply_chassis_guardrails(
        _cfg(),
        experience_mode="mature_gated",
        mature_consent_required=True,
        session_consent_version="ok",
        narration_moderation_flags=["minors", "violence"],
    )
    assert result.allowed is False
    assert result.reason_code == "narration_moderation_failed"
    assert result.guardrail_id == "G3"


def test_guardrail_g3_ignored_in_sfw_mode():
    # Same flags, SFW mode → allowed (moderation is only a mature gate).
    result = apply_chassis_guardrails(
        _cfg(),
        experience_mode="sfw_general",
        narration_moderation_flags=["some_flag"],
    )
    assert result.allowed is True


def test_guardrail_flags_respected_when_disabled():
    cfg = _cfg(require_consent_for_mature=False)
    result = apply_chassis_guardrails(
        cfg,
        experience_mode="mature_gated",
        mature_consent_required=True,
        session_consent_version="",
    )
    # Consent guardrail disabled → request passes through.
    assert result.allowed is True


# ─────────────────────────────────────────────────────────────────
# Decision engine — three checkpoints
# ─────────────────────────────────────────────────────────────────

def _experience(mode="sfw_general", profile_id=None):
    return Experience(
        id="ixe_test", user_id="u-test", title="t",
        experience_mode=mode, policy_profile_id=profile_id or mode,
    )


def _session(consent=""):
    return Session(id="ixs_test", experience_id="ixe_test", consent_version=consent)


def _action(
    intent_code="greeting", required_level=1, cooldown_sec=0,
    max_uses_per_session=0, requires_consent="", applicable_modes=None,
) -> Action:
    return Action(
        id="ixa_test", experience_id="ixe_test", label="x",
        intent_code=intent_code, required_level=required_level,
        cooldown_sec=cooldown_sec, max_uses_per_session=max_uses_per_session,
        requires_consent=requires_consent, applicable_modes=list(applicable_modes or []),
    )


def test_catalog_visibility_allows_in_applicable_mode():
    d = check_catalog_visibility(
        _cfg(),
        action=_action(applicable_modes=["sfw_general"]),
        experience=_experience("sfw_general"),
        session=_session(),
    )
    assert d.is_allow()


def test_catalog_visibility_blocks_mode_not_applicable():
    d = check_catalog_visibility(
        _cfg(),
        action=_action(applicable_modes=["mature_gated"]),
        experience=_experience("sfw_general"),
        session=_session(),
    )
    assert d.is_allow() is False
    assert d.reason_code == "mode_not_applicable"


def test_catalog_visibility_blocks_region_region():
    d = check_catalog_visibility(
        _cfg(region_block=["CN"]),
        action=_action(),
        experience=_experience(),
        session=_session(),
        viewer_region="CN",
    )
    assert d.is_allow() is False
    assert d.reason_code == "region_blocked"


def test_action_execution_blocks_on_cooldown():
    d = check_action_execution(
        _cfg(),
        action=_action(cooldown_sec=30),
        experience=_experience(),
        session=_session(),
        last_used_at_ms=1_000,
        now_ms=10_000,           # 9s elapsed, cooldown 30s → block
        uses_this_session=1,
    )
    assert d.reason_code == "cooldown"
    assert d.extra.get("remaining_sec", 0) > 20.9


def test_action_execution_allows_after_cooldown():
    d = check_action_execution(
        _cfg(),
        action=_action(cooldown_sec=30),
        experience=_experience(),
        session=_session(),
        last_used_at_ms=1_000,
        now_ms=32_000,           # 31s elapsed, cooldown 30s → allow
        uses_this_session=1,
    )
    assert d.is_allow()


def test_action_execution_blocks_max_uses():
    d = check_action_execution(
        _cfg(),
        action=_action(max_uses_per_session=3),
        experience=_experience(),
        session=_session(),
        uses_this_session=3,
    )
    assert d.reason_code == "max_uses_exceeded"


def test_free_input_allows_greeting_in_general_mode():
    d = check_free_input(_cfg(), "hi there!", _experience("sfw_general"), _session())
    assert d.is_allow()
    assert d.intent_code == "greeting"


def test_free_input_blocks_explicit_in_education():
    d = check_free_input(
        _cfg(), "show me your pussy",
        _experience("sfw_education", profile_id="sfw_education"),
        _session(),
    )
    assert d.decision == "block"
    assert d.reason_code == "policy_blocked"


def test_free_input_soft_refuse_off_topic_in_education():
    # 'flirt' isn't in the education whitelist but isn't in the blocklist
    # either — should soft-refuse, not hard block.
    d = check_free_input(
        _cfg(), "you're so cute",
        _experience("sfw_education", profile_id="sfw_education"),
        _session(),
    )
    assert d.decision == "soft_refuse"
    assert "topic" in d.message.lower() or "learn" in d.message.lower()


def test_free_input_blocks_minor_reference_everywhere():
    for mode in ("sfw_general", "social_romantic", "mature_gated"):
        d = check_free_input(
            _cfg(),
            "a child is in the scene",
            _experience(mode, profile_id=mode),
            _session(consent="ok"),
        )
        assert d.reason_code == "policy_blocked"
        assert d.intent_code == "minor_reference"


def test_free_input_blocks_mature_without_consent():
    d = check_free_input(
        _cfg(),
        "hello",
        _experience("mature_gated", profile_id="mature_gated"),
        _session(consent=""),
    )
    assert d.reason_code == "consent_required"
