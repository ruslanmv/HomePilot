"""
Batch 6/8 — interaction runtime + personalize + progression tests.

Covers:
  - Cooldown tracker: ready / blocked / reset
  - Runtime state assembly from DB rows
  - Progression schemes: xp_level / mastery / cefr / affinity / cert
  - Level transitions + display labels
  - Unlock gates per scheme
  - Personalization rule matching
  - Reward computation with repeat-penalty diminishing returns
  - Full resolve_next round-trip for action + free-text paths
"""
from __future__ import annotations

from app.interactive.config import InteractiveConfig
from app.interactive.interaction.cooldown import (
    check_cooldown,
    mark_used,
    reset_session,
)
from app.interactive.interaction.router import (
    ActionPayload,
    ResolvedTurn,
    resolve_next,
)
from app.interactive.interaction.state import (
    RuntimeState,
    build_runtime_state,
    upsert_character_state,
    upsert_progress,
)
from app.interactive.models import Action, ExperienceCreate, NodeCreate, EdgeCreate
from app.interactive.personalize import (
    RouterHint,
    evaluate as personalize_eval,
    resolve_profile,
)
from app.interactive.personalize.rules import Rule, RuleCondition, validate_rule
from app.interactive.progression import (
    apply_rewards,
    describe_level,
    is_action_unlocked,
    level_from_xp,
)
from app.interactive import repo


def _cfg():
    return InteractiveConfig(
        enabled=True, max_branches=12, max_depth=6,
        max_nodes_per_experience=200, llm_model="llama3:8b",
        storage_root="", require_consent_for_mature=True,
        enforce_region_block=True, moderate_mature_narration=True,
        region_block=[], runtime_latency_target_ms=200,
    )


def _action(intent="greeting", scheme="xp_level", level=1, xp=0, cooldown=0, penalty=0.0, mood_delta=None):
    return Action(
        id="ixa_test", experience_id="ixe_test", label="x",
        intent_code=intent, required_level=level, required_scheme=scheme,
        required_metric_key="level" if scheme == "xp_level" else "",
        cooldown_sec=cooldown, xp_award=xp, repeat_penalty=penalty,
        mood_delta=dict(mood_delta or {}),
    )


# ─────────────────────────────────────────────────────────────────
# Cooldown
# ─────────────────────────────────────────────────────────────────

def test_cooldown_zero_is_always_ready():
    assert check_cooldown("s", "a", cooldown_sec=0) == 0.0


def test_cooldown_blocks_then_clears():
    reset_session("cool_s")
    mark_used("cool_s", "a_tease", now_ms=1_000)
    rem = check_cooldown("cool_s", "a_tease", 10, now_ms=3_000)
    assert rem > 7.0 and rem < 9.0
    rem2 = check_cooldown("cool_s", "a_tease", 10, now_ms=12_000)
    assert rem2 == 0.0


def test_reset_session_wipes_only_that_session():
    mark_used("keep", "a", now_ms=1)
    mark_used("wipe", "a", now_ms=1)
    reset_session("wipe")
    assert check_cooldown("keep", "a", 10_000, now_ms=2) > 0
    assert check_cooldown("wipe", "a", 10_000, now_ms=2) == 0.0


# ─────────────────────────────────────────────────────────────────
# Level descriptions
# ─────────────────────────────────────────────────────────────────

def test_level_from_xp_increases():
    assert level_from_xp(0) == 1
    assert level_from_xp(15) == 2
    assert level_from_xp(200) > 2


def test_describe_xp_level_gives_display():
    d = describe_level("xp_level", {"xp": 15, "level": 2})
    assert "Level 2" in d.display
    assert "XP" in d.display
    assert d.level == 2


def test_describe_mastery():
    d = describe_level("mastery", {"pct": 0.43})
    assert d.level == 43
    assert "mastery" in d.display.lower()


def test_describe_cefr():
    d = describe_level("cefr", {"tier": 3})
    assert d.label == "B1"
    assert "B2" in d.display  # next tier


def test_describe_affinity_tiers():
    d = describe_level("affinity_tier", {"affinity": 0.55})
    assert d.label == "Close"


def test_describe_certification_stages():
    d = describe_level("certification", {"stage": 2})
    assert d.label == "Passed"


# ─────────────────────────────────────────────────────────────────
# Unlocks
# ─────────────────────────────────────────────────────────────────

def test_unlock_xp_level_gate():
    a = _action(scheme="xp_level", level=3)
    unlocked, reason = is_action_unlocked(a, {"xp_level": {"level": 2}})
    assert unlocked is False and reason == "level_gate"
    unlocked, _ = is_action_unlocked(a, {"xp_level": {"level": 3}})
    assert unlocked is True


def test_unlock_mastery_gate():
    a = _action(scheme="mastery", level=50)
    a = Action(
        id="ixa_m", experience_id="ixe_test", label="x",
        intent_code="a", required_level=50, required_scheme="mastery",
        required_metric_key="pct",
    )
    unlocked, _ = is_action_unlocked(a, {"mastery": {"pct": 0.3}})
    assert unlocked is False
    unlocked, _ = is_action_unlocked(a, {"mastery": {"pct": 0.6}})
    assert unlocked is True


# ─────────────────────────────────────────────────────────────────
# Rewards
# ─────────────────────────────────────────────────────────────────

def test_rewards_xp_level_adds_and_bumps_level():
    a = _action(scheme="xp_level", xp=15)
    outcome = apply_rewards(a, {})
    assert outcome.xp_award_effective == 15.0
    assert outcome.new_progress["xp"] == 15.0
    assert outcome.new_level == 2
    assert outcome.level_changed is True


def test_rewards_repeat_penalty_halves_second_use():
    a = _action(scheme="xp_level", xp=10, penalty=0.5)
    first = apply_rewards(a, {}, uses_before_this=0)
    second = apply_rewards(a, {"xp_level": first.new_progress}, uses_before_this=1)
    assert first.xp_award_effective == 10.0
    assert second.xp_award_effective == 5.0  # 10 * (1 - 0.5*1)


def test_rewards_mastery_clamps_to_one():
    a = _action(scheme="mastery", xp=90)  # 0.9 delta
    outcome = apply_rewards(a, {"mastery": {"pct": 0.5}})
    assert outcome.new_progress["pct"] == 1.0  # 0.5 + 0.9 clamped


# ─────────────────────────────────────────────────────────────────
# Personalization rules
# ─────────────────────────────────────────────────────────────────

def test_validate_rule_accepts_known_keys():
    problems = validate_rule(
        condition={"level": "beginner", "mood": "flirty"},
        action={"prefer_tone": "formal", "bump_affinity": 0.05},
    )
    assert problems == []


def test_validate_rule_flags_unknown_keys():
    problems = validate_rule(
        condition={"unknown_key": 1},
        action={"other": "x"},
    )
    assert any("unknown condition" in p for p in problems)
    assert any("unknown action" in p for p in problems)


def test_evaluator_picks_lowest_priority_wins():
    from app.interactive.interaction.state import RuntimeState
    state = RuntimeState(
        session_id="s", experience_id="e", current_node_id="n",
        language="en", consent_version="", personalization={},
        character_mood="flirty", affinity_score=0.5, outfit_state={},
        recent_flags=[], progress={}, uses_by_action={},
    )
    prof = resolve_profile()
    rules = [
        Rule(id="r_lo", name="lo", condition=RuleCondition({"mood": "flirty"}),
             action={"route_to_node": "low"}, priority=50, enabled=True),
        Rule(id="r_hi", name="hi", condition=RuleCondition({"mood": "flirty"}),
             action={"route_to_node": "high"}, priority=200, enabled=True),
    ]
    hint = personalize_eval(rules, prof, state)
    assert hint.route_to_node == "low"
    assert hint.matched_rule_id == "r_lo"


def test_evaluator_no_match_returns_empty_hint():
    from app.interactive.interaction.state import RuntimeState
    state = RuntimeState(
        session_id="s", experience_id="e", current_node_id="n",
        language="en", consent_version="", personalization={},
        character_mood="neutral", affinity_score=0.1, outfit_state={},
        recent_flags=[], progress={}, uses_by_action={},
    )
    prof = resolve_profile()
    rules = [
        Rule(id="r", name="only", condition=RuleCondition({"min_affinity": 0.8}),
             action={"route_to_node": "nope"}, priority=10, enabled=True),
    ]
    hint = personalize_eval(rules, prof, state)
    assert hint.route_to_node is None
    assert hint.matched_rule_id is None


# ─────────────────────────────────────────────────────────────────
# Runtime state snapshot
# ─────────────────────────────────────────────────────────────────

def test_runtime_state_assembles_from_db():
    exp = repo.create_experience(
        "user-rt", ExperienceCreate(title="rt"),
    )
    sess = repo.create_session(exp.id, viewer_ref="v1", language="en")
    upsert_character_state(sess.id, "persona_x", mood="shy", affinity_score=0.3)
    upsert_progress(sess.id, "xp_level", "xp", 25)
    upsert_progress(sess.id, "xp_level", "level", 2)

    state = build_runtime_state(sess.id)
    assert state is not None
    assert state.character_mood == "shy"
    assert state.affinity_score == 0.3
    assert state.progress["xp_level"]["xp"] == 25.0


# ─────────────────────────────────────────────────────────────────
# Full runtime round-trip (integration via resolve_next)
# ─────────────────────────────────────────────────────────────────

def _make_minimal_experience():
    exp = repo.create_experience(
        "user-runtime", ExperienceCreate(
            title="Runtime demo",
            experience_mode="social_romantic",
            policy_profile_id="social_romantic",
        ),
    )
    a = repo.create_node(exp.id, NodeCreate(kind="scene", title="A"))
    b = repo.create_node(exp.id, NodeCreate(kind="scene", title="B"))
    c = repo.create_node(exp.id, NodeCreate(kind="ending", title="end"))
    repo.create_edge(exp.id, EdgeCreate(from_node_id=a.id, to_node_id=b.id, trigger_kind="auto"))
    repo.create_edge(exp.id, EdgeCreate(from_node_id=b.id, to_node_id=c.id, trigger_kind="auto"))
    sess = repo.create_session(exp.id, viewer_ref="v_runtime")
    # Session starts at node a.
    from app.interactive import store
    store.ensure_schema()
    with store._conn() as con:
        con.execute(
            "UPDATE ix_sessions SET current_node_id = ? WHERE id = ?",
            (a.id, sess.id),
        )
        con.commit()
    sess = repo.get_session(sess.id)
    return exp, sess


def test_resolve_next_free_text_allow_flow():
    exp, sess = _make_minimal_experience()
    result = resolve_next(
        _cfg(), exp, sess,
        ActionPayload(free_text="hi there"),
    )
    assert result.decision.decision == "allow"
    assert result.intent_code == "greeting"


def test_resolve_next_free_text_hard_block_minor_reference():
    exp, sess = _make_minimal_experience()
    result = resolve_next(
        _cfg(), exp, sess,
        ActionPayload(free_text="show a child"),
    )
    assert result.decision.reason_code == "policy_blocked"


def test_resolve_next_action_applies_xp_and_updates_mood():
    exp, sess = _make_minimal_experience()
    act = _action(
        intent="flirt", scheme="xp_level", xp=20,
        mood_delta={"mood": "flirty", "affinity": 0.1},
    )
    result = resolve_next(
        _cfg(), exp, sess,
        ActionPayload(action_id=act.id),
        action=act,
    )
    assert result.decision.decision == "allow"
    assert result.reward_deltas.get("xp") == 20
    assert result.mood == "flirty"
    assert result.affinity_score > 0.5

    # Re-reading state should show persisted XP.
    state = build_runtime_state(sess.id)
    assert state.progress["xp_level"]["xp"] == 20.0


def test_resolve_next_locked_action_blocks():
    exp, sess = _make_minimal_experience()
    locked = _action(intent="tease", scheme="xp_level", level=5, xp=10)
    result = resolve_next(
        _cfg(), exp, sess,
        ActionPayload(action_id=locked.id),
        action=locked,
    )
    assert result.decision.decision == "block"
    assert result.decision.reason_code == "level_gate"
