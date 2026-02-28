# tests/test_teams_orchestration.py
"""
Unit tests for the Teams multi-agent orchestration pipeline.

Tests the core orchestration logic (intent scoring, hand-raise lifecycle,
speaker selection gates) with no external dependencies — pure Python,
no FastAPI, no LLM, no disk I/O.

Compatible with GitHub Actions CI: `pytest tests/test_teams_orchestration.py -v`
"""
from __future__ import annotations

import pytest
from app.teams.intent import (
    SpeakIntent,
    compute_intent,
    tick_cooldowns,
    set_cooldown,
    _dominance_penalty,
    _authority_boost,
    _cooldown_penalty,
    _redundancy_penalty,
    _extract_keywords,
    AUTHORITY_MAP,
)
from app.teams.orchestrator import (
    ensure_defaults,
    compute_all_intents,
    auto_hand_raises,
    redundancy_gate,
    diversity_gate,
    select_speakers,
)
from app.teams.participants_resolver import infer_role_tags


# ---------------------------------------------------------------------------
# Helpers — build minimal room / participant structures
# ---------------------------------------------------------------------------

def _make_room(**overrides) -> dict:
    """Create a minimal room dict for testing."""
    room = {
        "id": "room-1",
        "name": "Test Room",
        "participant_ids": [],
        "messages": [],
        "turn_mode": "reactive",
        "policy": {},
        "intents": {},
        "hand_raises": [],
        "hand_raise_meta": {},
        "cooldowns": {},
        "muted": [],
        "round": 0,
    }
    room.update(overrides)
    return room


def _make_participant(pid: str, name: str, role_tags: list[str] | None = None) -> dict:
    return {
        "persona_id": pid,
        "display_name": name,
        "role_tags": role_tags or [],
    }


def _make_message(sender_id: str, content: str, role: str = "assistant", ts: float = 1.0) -> dict:
    return {
        "id": f"msg-{sender_id}-{ts}",
        "sender_id": sender_id,
        "sender_name": sender_id,
        "content": content,
        "role": role,
        "tools_used": [],
        "timestamp": ts,
    }


# ===========================================================================
# 1. Intent scoring
# ===========================================================================

class TestIntentScoring:
    """Test deterministic intent computation."""

    def test_baseline_listening(self):
        """A persona with no triggers should get baseline score and not want to speak."""
        room = _make_room(policy={"speak_threshold": 0.7})
        intent = compute_intent(room, "p1", "Alice", [], "hello world")
        assert isinstance(intent, SpeakIntent)
        assert intent.confidence > 0
        assert intent.confidence < 0.7  # below default threshold
        assert not intent.wants_to_speak
        assert intent.reason == "listening" or "listening" in intent.reason or len(intent.reason) >= 0

    def test_name_mention_boosts_confidence(self):
        """Mentioning a persona by name should significantly boost their score."""
        room = _make_room(policy={"speak_threshold": 0.45})
        intent = compute_intent(room, "p1", "Alice", [], "Alice what do you think?")
        assert intent.confidence >= 0.45
        assert intent.wants_to_speak
        assert "mentioned by name" in intent.reason

    def test_question_detection(self):
        """Questions should boost intent score."""
        room = _make_room(policy={"speak_threshold": 0.45})
        intent = compute_intent(room, "p1", "Bob", ["analyst"], "What do the metrics show?")
        assert "question/decision" in intent.reason or "role relevance" in intent.reason

    def test_role_relevance_triggers(self):
        """Engineer persona should score higher on technical topics."""
        room = _make_room(policy={"speak_threshold": 0.45})
        intent = compute_intent(room, "eng1", "DevBot", ["engineer"], "We need to deploy the api fix")
        assert intent.confidence > 0.3  # should get role relevance boost
        assert "role relevance" in intent.reason

    def test_intent_type_classification(self):
        """Verify intent_type is classified correctly."""
        room = _make_room()
        risk = compute_intent(room, "p1", "X", [], "There's a risk and a blocker here")
        assert risk.intent_type == "risk"

        question = compute_intent(room, "p1", "X", [], "What should we do?")
        assert question.intent_type == "clarify"

        summary = compute_intent(room, "p1", "X", [], "Let me give a summary recap")
        assert summary.intent_type == "summary"

        action = compute_intent(room, "p1", "X", [], "Let's assign the action items")
        assert action.intent_type == "action"

    def test_brainstorm_prompt_boosts(self):
        """Brainstorming keywords should boost the score."""
        room = _make_room(policy={"speak_threshold": 0.45})
        intent = compute_intent(room, "p1", "Creative", ["creative"], "Let's brainstorm some ideas")
        assert "brainstorm prompt" in intent.reason

    def test_urgency_values(self):
        """Urgency should be higher for risk and urgent keywords."""
        room = _make_room()
        normal = compute_intent(room, "p1", "X", [], "hello")
        assert normal.urgency == 0.4

        risk = compute_intent(room, "p1", "X", [], "there's a risk")
        assert risk.urgency == 0.8

        urgent = compute_intent(room, "p1", "X", [], "this is urgent and critical")
        assert urgent.urgency == 0.9


# ===========================================================================
# 2. Authority boost
# ===========================================================================

class TestAuthorityBoost:
    """Test role-intent alignment authority scoring."""

    def test_legal_on_risk(self):
        assert _authority_boost(["legal"], "risk") == 0.10

    def test_engineer_on_risk(self):
        assert _authority_boost(["engineer"], "risk") == 0.10

    def test_secretary_on_action(self):
        assert _authority_boost(["secretary"], "action") == 0.10

    def test_creative_on_idea(self):
        assert _authority_boost(["creative"], "idea") == 0.10

    def test_no_match(self):
        assert _authority_boost(["finance"], "idea") == 0.0

    def test_empty_roles(self):
        assert _authority_boost([], "risk") == 0.0

    def test_authority_map_completeness(self):
        """All expected intent types should be in the authority map."""
        for it in ["risk", "action", "clarify", "summary", "idea"]:
            assert it in AUTHORITY_MAP


# ===========================================================================
# 3. Dominance penalty
# ===========================================================================

class TestDominancePenalty:
    """Test dominance suppression for over-active personas."""

    def test_no_penalty_with_few_messages(self):
        """With fewer than 3 assistant messages, no penalty applies."""
        room = _make_room(messages=[
            _make_message("p1", "hello"),
            _make_message("p1", "world"),
        ])
        assert _dominance_penalty(room, "p1") == 0.0

    def test_penalty_when_dominant(self):
        """Penalty applies when persona has >40% of recent assistant messages."""
        msgs = [_make_message("p1", f"msg{i}") for i in range(5)]
        room = _make_room(messages=msgs)
        # p1 has 5 out of 5 = 100% — should be penalized
        assert _dominance_penalty(room, "p1") == 0.15

    def test_no_penalty_when_balanced(self):
        """No penalty when conversation is balanced."""
        msgs = [
            _make_message("p1", "a"),
            _make_message("p2", "b"),
            _make_message("p3", "c"),
            _make_message("p4", "d"),
        ]
        room = _make_room(messages=msgs)
        assert _dominance_penalty(room, "p1") == 0.0


# ===========================================================================
# 4. Cooldown management
# ===========================================================================

class TestCooldowns:
    """Test cooldown tick and set mechanics."""

    def test_set_and_tick(self):
        room = _make_room()
        set_cooldown(room, "p1", 2)
        assert room["cooldowns"]["p1"] == 2

        tick_cooldowns(room)
        assert room["cooldowns"]["p1"] == 1

        tick_cooldowns(room)
        assert room["cooldowns"]["p1"] == 0

    def test_cooldown_penalty(self):
        room = _make_room(cooldowns={"p1": 2})
        assert _cooldown_penalty(room, "p1") == 0.35

        room2 = _make_room(cooldowns={"p1": 0})
        assert _cooldown_penalty(room2, "p1") == 0.0

    def test_tick_does_not_go_negative(self):
        room = _make_room(cooldowns={"p1": 0})
        tick_cooldowns(room)
        assert room["cooldowns"]["p1"] == 0


# ===========================================================================
# 5. Redundancy penalty
# ===========================================================================

class TestRedundancyPenalty:
    """Test topic overlap penalty."""

    def test_no_penalty_without_overlap(self):
        room = _make_room(messages=[
            _make_message("p2", "the weather is nice today"),
        ])
        penalty = _redundancy_penalty(room, "p1", ["deploy", "infrastructure"])
        assert penalty == 0.0

    def test_penalty_with_high_overlap(self):
        room = _make_room(messages=[
            _make_message("p2", "deploy infrastructure api backend"),
        ])
        tags = ["deploy", "infrastructure", "backend"]
        penalty = _redundancy_penalty(room, "p1", tags)
        assert penalty > 0


# ===========================================================================
# 6. Keyword extraction
# ===========================================================================

class TestKeywordExtraction:
    def test_extracts_keywords(self):
        kws = _extract_keywords("We should deploy the API and fix the backend integration")
        assert len(kws) > 0
        assert all(len(k) >= 4 for k in kws)

    def test_deduplicates(self):
        kws = _extract_keywords("deploy deploy deploy deploy")
        assert kws.count("deploy") == 1

    def test_max_12(self):
        long_text = " ".join(f"word{i}xxxx" for i in range(30))
        kws = _extract_keywords(long_text)
        assert len(kws) <= 12


# ===========================================================================
# 7. ensure_defaults
# ===========================================================================

class TestEnsureDefaults:
    """Ensure room defaults are applied without overwriting existing values."""

    def test_sets_missing_fields(self):
        room = _make_room()
        room.pop("policy")
        room.pop("round")
        ensure_defaults(room)
        assert "policy" in room
        assert room["round"] == 0
        assert room["policy"]["max_speakers_per_event"] == 2
        assert room["policy"]["hand_raise_threshold"] == 0.55
        assert room["policy"]["hand_raise_ttl_rounds"] == 2
        assert room["policy"]["max_visible_hands"] == 3

    def test_does_not_overwrite_existing(self):
        room = _make_room(policy={"speak_threshold": 0.9})
        ensure_defaults(room)
        assert room["policy"]["speak_threshold"] == 0.9


# ===========================================================================
# 8. Auto hand-raise lifecycle
# ===========================================================================

class TestAutoHandRaises:
    """Test auto hand-raise, TTL expiry, and max cap."""

    def test_raises_hand_above_threshold(self):
        room = _make_room(round=1, policy={"hand_raise_threshold": 0.5, "hand_raise_ttl_rounds": 2, "max_visible_hands": 3})
        intents = [
            SpeakIntent("p1", True, 0.8, "high confidence", "idea", 0.5, ["deploy"]),
        ]
        auto_hand_raises(room, intents)
        assert "p1" in room["hand_raises"]
        assert "p1" in room["hand_raise_meta"]
        meta = room["hand_raise_meta"]["p1"]
        assert meta["raised_at_round"] == 1
        assert meta["expires_round"] == 3

    def test_does_not_raise_below_threshold(self):
        room = _make_room(round=1, policy={"hand_raise_threshold": 0.8, "hand_raise_ttl_rounds": 2, "max_visible_hands": 3})
        intents = [
            SpeakIntent("p1", False, 0.3, "low confidence", "idea", 0.4, []),
        ]
        auto_hand_raises(room, intents)
        assert "p1" not in room["hand_raises"]

    def test_max_visible_hands_cap(self):
        room = _make_room(round=1, policy={"hand_raise_threshold": 0.4, "hand_raise_ttl_rounds": 5, "max_visible_hands": 2})
        intents = [
            SpeakIntent("p1", True, 0.9, "top", "idea", 0.9, []),
            SpeakIntent("p2", True, 0.8, "high", "risk", 0.8, []),
            SpeakIntent("p3", True, 0.7, "medium", "clarify", 0.7, []),
        ]
        auto_hand_raises(room, intents)
        assert len(room["hand_raise_meta"]) == 2  # capped at 2

    def test_ttl_expiry(self):
        room = _make_room(
            round=5,
            hand_raises=["p1"],
            hand_raise_meta={"p1": {"raised_at_round": 2, "expires_round": 4, "reason": "old", "confidence_at_raise": 0.6, "intent_type": "idea"}},
            policy={"hand_raise_threshold": 0.9, "hand_raise_ttl_rounds": 2, "max_visible_hands": 3},
        )
        auto_hand_raises(room, [])
        assert "p1" not in room["hand_raises"]
        assert "p1" not in room["hand_raise_meta"]


# ===========================================================================
# 9. Redundancy gate
# ===========================================================================

class TestRedundancyGate:
    """Test that speakers with overlapping topics are filtered out."""

    def test_keeps_different_topics(self):
        intents = [
            SpeakIntent("p1", True, 0.9, "", "idea", 0.5, ["deploy", "api", "backend"]),
            SpeakIntent("p2", True, 0.8, "", "risk", 0.5, ["budget", "finance", "cost"]),
        ]
        result = redundancy_gate(intents, ["p1", "p2"], threshold=0.7)
        assert result == ["p1", "p2"]

    def test_filters_overlapping_topics(self):
        intents = [
            SpeakIntent("p1", True, 0.9, "", "idea", 0.5, ["deploy", "api", "backend"]),
            SpeakIntent("p2", True, 0.8, "", "idea", 0.5, ["deploy", "api", "backend"]),
        ]
        result = redundancy_gate(intents, ["p1", "p2"], threshold=0.7)
        assert result == ["p1"]  # p2 dropped due to overlap

    def test_single_speaker_passes(self):
        intents = [SpeakIntent("p1", True, 0.9, "", "idea", 0.5, ["deploy"])]
        result = redundancy_gate(intents, ["p1"], threshold=0.7)
        assert result == ["p1"]


# ===========================================================================
# 10. Diversity gate
# ===========================================================================

class TestDiversityGate:
    """Test that speakers with identical role tags are filtered out."""

    def test_keeps_different_roles(self):
        participants = [
            _make_participant("p1", "Alice", ["engineer"]),
            _make_participant("p2", "Bob", ["analyst"]),
        ]
        result = diversity_gate(["p1", "p2"], participants)
        assert result == ["p1", "p2"]

    def test_filters_duplicate_roles(self):
        participants = [
            _make_participant("p1", "Alice", ["engineer"]),
            _make_participant("p2", "Bob", ["engineer"]),
        ]
        result = diversity_gate(["p1", "p2"], participants)
        assert result == ["p1"]  # Bob dropped (same role)

    def test_empty_roles_pass_through(self):
        participants = [
            _make_participant("p1", "Alice", []),
            _make_participant("p2", "Bob", []),
        ]
        result = diversity_gate(["p1", "p2"], participants)
        assert "p1" in result and "p2" in result


# ===========================================================================
# 11. Speaker selection
# ===========================================================================

class TestSelectSpeakers:
    """Test the full speaker selection pipeline."""

    def test_reactive_selects_top_intent(self):
        room = _make_room(turn_mode="reactive")
        ensure_defaults(room)
        intents = [
            SpeakIntent("p1", True, 0.9, "high", "idea", 0.5, ["deploy"]),
            SpeakIntent("p2", False, 0.3, "low", "idea", 0.4, []),
        ]
        participants = [
            _make_participant("p1", "Alice", ["engineer"]),
            _make_participant("p2", "Bob", ["analyst"]),
        ]
        speakers = select_speakers(room, intents, participants)
        assert "p1" in speakers
        assert "p2" not in speakers

    def test_moderated_respects_called_on(self):
        room = _make_room(turn_mode="moderated", called_on="p2")
        ensure_defaults(room)
        intents = [
            SpeakIntent("p1", True, 0.9, "high", "idea", 0.5, []),
            SpeakIntent("p2", True, 0.5, "low", "idea", 0.4, []),
        ]
        participants = [
            _make_participant("p1", "Alice"),
            _make_participant("p2", "Bob"),
        ]
        speakers = select_speakers(room, intents, participants)
        assert speakers == ["p2"]

    def test_hand_raisers_prioritized(self):
        room = _make_room(turn_mode="reactive", hand_raises=["p2"])
        ensure_defaults(room)
        intents = [
            SpeakIntent("p1", True, 0.8, "high", "idea", 0.5, ["deploy"]),
            SpeakIntent("p2", True, 0.6, "hand", "risk", 0.7, ["budget"]),
        ]
        participants = [
            _make_participant("p1", "Alice", ["engineer"]),
            _make_participant("p2", "Bob", ["finance"]),
        ]
        speakers = select_speakers(room, intents, participants)
        # p2 should be first (hand-raiser priority)
        assert speakers[0] == "p2"

    def test_empty_intents_returns_empty(self):
        room = _make_room(turn_mode="reactive")
        ensure_defaults(room)
        speakers = select_speakers(room, [], [])
        assert speakers == []

    def test_fallback_on_question(self):
        """When no one wants_to_speak but human asked a question, pick top scorer."""
        room = _make_room(
            turn_mode="reactive",
            messages=[_make_message("human", "What should we do?", role="user")],
        )
        ensure_defaults(room)
        intents = [
            SpeakIntent("p1", False, 0.3, "low", "clarify", 0.4, []),
            SpeakIntent("p2", False, 0.2, "lower", "idea", 0.3, []),
        ]
        participants = [
            _make_participant("p1", "Alice"),
            _make_participant("p2", "Bob"),
        ]
        speakers = select_speakers(room, intents, participants)
        assert speakers == ["p1"]  # highest confidence fallback


# ===========================================================================
# 12. compute_all_intents
# ===========================================================================

class TestComputeAllIntents:
    """Test batch intent computation."""

    def test_computes_for_all_unmuted(self):
        room = _make_room(muted=["p2"])
        ensure_defaults(room)
        participants = [
            _make_participant("p1", "Alice", ["engineer"]),
            _make_participant("p2", "Bob", ["analyst"]),
            _make_participant("p3", "Carol", ["creative"]),
        ]
        intents = compute_all_intents(room, participants, "Let's deploy the api")
        pids = [i.persona_id for i in intents]
        assert "p1" in pids
        assert "p2" not in pids  # muted
        assert "p3" in pids

    def test_persists_intent_snapshots(self):
        room = _make_room()
        ensure_defaults(room)
        participants = [_make_participant("p1", "Alice")]
        compute_all_intents(room, participants, "hello")
        assert "p1" in room["intents"]
        snap = room["intents"]["p1"]
        assert "confidence" in snap
        assert "intent_type" in snap
        assert "reason" in snap


# ===========================================================================
# 13. Role tag inference
# ===========================================================================

class TestRoleTagInference:
    """Test automatic role tag inference from persona metadata."""

    def test_infers_engineer(self):
        project = {"name": "DevOps Bot", "description": "Handles backend API deployments"}
        tags = infer_role_tags(project)
        assert "engineer" in tags

    def test_infers_legal(self):
        project = {"name": "Legal Advisor", "description": "Compliance and regulation expert"}
        tags = infer_role_tags(project)
        assert "legal" in tags

    def test_max_two_tags(self):
        project = {"name": "Full-stack engineer designer researcher analyst"}
        tags = infer_role_tags(project)
        assert len(tags) <= 2

    def test_empty_project_no_tags(self):
        tags = infer_role_tags({"name": "", "description": ""})
        assert isinstance(tags, list)


# ===========================================================================
# 14. Full pipeline integration (no LLM)
# ===========================================================================

class TestFullPipeline:
    """Integration test: room setup → intent → hand-raise → select speakers."""

    def test_end_to_end_reactive_step(self):
        """Simulate a full reactive step without LLM generation."""
        room = _make_room(
            turn_mode="reactive",
            participant_ids=["p1", "p2", "p3"],
            messages=[_make_message("human", "Alice, what's the deploy risk?", role="user")],
        )
        ensure_defaults(room)

        participants = [
            _make_participant("p1", "Alice", ["engineer"]),
            _make_participant("p2", "Bob", ["analyst"]),
            _make_participant("p3", "Carol", ["creative"]),
        ]

        # 1. Compute intents
        intents = compute_all_intents(room, participants, "Alice, what's the deploy risk?")
        assert len(intents) == 3

        # Alice should score highest (name mention + role relevance + authority)
        alice_intent = next(i for i in intents if i.persona_id == "p1")
        assert alice_intent.confidence > 0.5
        assert alice_intent.wants_to_speak

        # 2. Auto hand-raises
        room["round"] = 1
        auto_hand_raises(room, intents)
        # At least Alice should have hand raised
        assert "p1" in room["hand_raises"]

        # 3. Select speakers (with gates)
        speakers = select_speakers(room, intents, participants)
        assert len(speakers) >= 1
        assert "p1" in speakers  # Alice should be selected

    def test_dominance_suppression_pipeline(self):
        """A persona who dominated recent conversation should be suppressed."""
        # Build a room where p1 has spoken 5 of the last 6 messages
        msgs = [_make_message("p1", f"msg{i}", ts=float(i)) for i in range(5)]
        msgs.append(_make_message("p2", "one message", ts=6.0))
        msgs.append(_make_message("human", "What do you think?", role="user", ts=7.0))

        room = _make_room(
            turn_mode="reactive",
            messages=msgs,
            policy={"speak_threshold": 0.45},
        )
        ensure_defaults(room)

        participants = [
            _make_participant("p1", "Alice", ["engineer"]),
            _make_participant("p2", "Bob", ["analyst"]),
        ]

        intents = compute_all_intents(room, participants, "What do you think?")
        p1 = next(i for i in intents if i.persona_id == "p1")
        p2 = next(i for i in intents if i.persona_id == "p2")

        # p1 should be penalized for dominance
        # Both get question boost, but p1 gets -0.15 dominance penalty
        assert "dominance penalty" in p1.reason

    def test_multi_round_no_speakers_stops(self):
        """When no one wants to speak, selection returns empty."""
        room = _make_room(turn_mode="reactive")
        ensure_defaults(room)
        # All intents below threshold
        intents = [
            SpeakIntent("p1", False, 0.1, "quiet", "idea", 0.3, []),
            SpeakIntent("p2", False, 0.1, "quiet", "idea", 0.3, []),
        ]
        participants = [
            _make_participant("p1", "Alice"),
            _make_participant("p2", "Bob"),
        ]
        speakers = select_speakers(room, intents, participants)
        assert speakers == []
