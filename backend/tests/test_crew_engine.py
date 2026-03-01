# tests/test_crew_engine.py
"""
Unit tests for the CrewAI-style Crew Workflow Engine.

Tests cover:
  - Profile registry (crew_profiles.py)
  - Output contract validation (section parsing, word count, budget limits)
  - Speaker selection for stages (preferred tags, round-robin, anti-repeat)
  - Checklist heuristics (task_planner_v1, brainstorm_v1, draft_and_edit_v1)
  - Novelty detection (Jaccard similarity)
  - Engine defaults and dispatch wiring
  - Full run_crew_turn() integration with mocked LLM

Pure Python — no FastAPI, no disk I/O, no real LLM calls.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.teams.crew_profiles import (
    WorkflowProfile,
    StageSpec,
    OutputContract,
    StopRules,
    get_profile,
    list_profiles,
    register_profile,
)
from app.teams import crew_engine as _crew_engine_mod
from app.teams.crew_engine import (
    _extract_sections,
    _word_count,
    _validate_output,
    _pick_speaker_for_stage,
    _update_checklist,
    _is_checklist_complete,
    _default_checklist,
    _safe_fallback,
    _tok,
    _jaccard,
    run_crew_turn,
)
from app.teams.orchestrator import ensure_defaults


# ── Helpers ───────────────────────────────────────────────────────────────


def _make_room(**overrides) -> dict:
    """Minimal room dict for testing."""
    room = {
        "id": "room-crew-1",
        "name": "Test Crew Room",
        "description": "Plan a date night under €30",
        "topic": "Date night planning under €30",
        "participant_ids": ["persona-a", "persona-b"],
        "messages": [],
        "turn_mode": "reactive",
        "agenda": ["Food", "Activity", "Budget"],
        "policy": {"engine": "crew", "crew": {"profile_id": "task_planner_v1"}},
        "state": {},
        "intents": {},
        "hand_raises": [],
        "hand_raise_meta": {},
        "cooldowns": {},
        "muted": [],
        "round": 0,
    }
    room.update(overrides)
    return room


def _make_participant(pid: str, name: str, role_tags: list = None) -> dict:
    return {
        "persona_id": pid,
        "display_name": name,
        "role_tags": role_tags or [],
    }


def _make_project(pid: str, name: str) -> dict:
    return {
        "id": pid,
        "name": name,
        "description": f"Test persona {name}",
        "persona_agent": {"label": name, "role": "assistant"},
        "instructions": "",
    }


# ── Profile registry ─────────────────────────────────────────────────────


class TestProfileRegistry:
    """Tests for crew_profiles.py profile registry."""

    def test_task_planner_v1_exists(self):
        p = get_profile("task_planner_v1")
        assert p is not None
        assert p.id == "task_planner_v1"
        assert len(p.stages) == 4
        assert p.stages[0].id == "gather_requirements"
        assert p.stages[-1].id == "finalize"

    def test_brainstorm_v1_exists(self):
        p = get_profile("brainstorm_v1")
        assert p is not None
        assert p.id == "brainstorm_v1"
        assert len(p.stages) == 3

    def test_draft_and_edit_v1_exists(self):
        p = get_profile("draft_and_edit_v1")
        assert p is not None
        assert len(p.stages) == 3

    def test_unknown_profile_returns_none(self):
        assert get_profile("nonexistent_profile") is None

    def test_list_profiles_returns_all(self):
        profiles = list_profiles()
        ids = [p["id"] for p in profiles]
        assert "task_planner_v1" in ids
        assert "brainstorm_v1" in ids
        assert "draft_and_edit_v1" in ids

    def test_profile_stages_have_preferred_tags(self):
        p = get_profile("task_planner_v1")
        for stage in p.stages:
            assert isinstance(stage.preferred_tags, list)
            assert stage.id  # non-empty

    def test_output_contract_has_required_fields(self):
        p = get_profile("task_planner_v1")
        c = p.output_contract
        assert c.format == "structured_text"
        assert c.max_words > 0

    def test_stop_rules_have_defaults(self):
        p = get_profile("task_planner_v1")
        sr = p.stop_rules
        assert sr.stop_when_complete is True
        assert sr.stop_on_low_novelty is True
        assert sr.low_novelty_window > 0
        assert 0.0 < sr.low_novelty_threshold < 1.0
        assert sr.max_no_progress_steps > 0


# ── Section extraction ────────────────────────────────────────────────────


class TestSectionExtraction:
    """Tests for _extract_sections()."""

    def test_basic_extraction(self):
        text = "PLAN:\n1) Cook dinner\n2) Watch movie\n\nBUDGET:\n- Total: €25\n\nMESSAGE:\nLet's go!"
        sections = _extract_sections(text)
        assert "PLAN" in sections
        assert "BUDGET" in sections
        assert "MESSAGE" in sections
        assert "Cook dinner" in sections["PLAN"]
        assert "€25" in sections["BUDGET"]

    def test_empty_text(self):
        assert _extract_sections("") == {}
        assert _extract_sections(None) == {}

    def test_no_sections(self):
        assert _extract_sections("Just some plain text without section headers.") == {}

    def test_single_section(self):
        text = "IDEAS:\n1) Build a chatbot\n2) Create a dashboard"
        sections = _extract_sections(text)
        assert "IDEAS" in sections
        assert "chatbot" in sections["IDEAS"]

    def test_section_names_are_uppercased(self):
        text = "PLAN:\nStep one\n\nBUDGET:\nLine items"
        sections = _extract_sections(text)
        assert "PLAN" in sections
        assert "BUDGET" in sections


# ── Output validation ─────────────────────────────────────────────────────


class TestOutputValidation:
    """Tests for _validate_output()."""

    def _profile(self):
        return get_profile("task_planner_v1")

    def test_valid_output(self):
        text = (
            "STEPS:\n1) Cook pasta at home\n2) Watch a movie on Netflix\n\n"
            "DETAILS:\n- Pasta ingredients: €10\n- Total: €10\n\n"
            "SUMMARY:\nA cozy night in with pasta and a movie!"
        )
        ok, reason, meta = _validate_output(
            profile=self._profile(), text=text, budget_limit=30.0,
        )
        assert ok is True
        assert reason == "ok"
        assert "sections" in meta

    def test_too_long_output(self):
        # Needs to exceed max_words (150)
        padding = " ".join(["word"] * 160)
        text = "Here is some content. " + padding
        ok, reason, _ = _validate_output(
            profile=self._profile(), text=text, budget_limit=None,
        )
        assert ok is False
        assert "too_long" in reason

    def test_too_short_output(self):
        text = "Just a few words."
        ok, reason, _ = _validate_output(
            profile=self._profile(), text=text, budget_limit=None,
        )
        assert ok is False
        assert "too_short" in reason

    def test_natural_text_without_sections_passes(self):
        text = (
            "I think we should start by preheating the oven to 325 degrees. "
            "Then we can mix the cream cheese with sugar and eggs. "
            "It's going to be delicious!"
        )
        ok, reason, _ = _validate_output(
            profile=self._profile(), text=text, budget_limit=None,
        )
        assert ok is True
        assert reason == "ok"

    def test_budget_over_limit(self):
        text = (
            "STEPS:\n1) Fancy restaurant\n\n"
            "DETAILS:\n- Dinner: €50\n- Total: €50\n\n"
            "SUMMARY:\nLet's splurge!"
        )
        ok, reason, _ = _validate_output(
            profile=self._profile(), text=text, budget_limit=30.0,
        )
        assert ok is False
        assert "budget_over_limit" in reason

    def test_budget_within_limit(self):
        text = (
            "STEPS:\n1) Cook at home\n\n"
            "DETAILS:\n- Groceries: €15\n- Total: €15\n\n"
            "SUMMARY:\nSimple and sweet."
        )
        ok, reason, _ = _validate_output(
            profile=self._profile(), text=text, budget_limit=30.0,
        )
        assert ok is True

    def test_no_budget_limit_passes(self):
        text = (
            "STEPS:\n1) Go skydiving\n\n"
            "DETAILS:\n- Jump: €500\n- Total: €500\n\n"
            "SUMMARY:\nYOLO!"
        )
        ok, reason, _ = _validate_output(
            profile=self._profile(), text=text, budget_limit=None,
        )
        assert ok is True

    def test_word_count(self):
        assert _word_count("hello world foo bar") == 4
        assert _word_count("") == 0
        assert _word_count("one") == 1


# ── Speaker selection for stages ──────────────────────────────────────────


class TestSpeakerSelection:
    """Tests for _pick_speaker_for_stage()."""

    def test_prefers_matching_role_tags(self):
        participants = [
            _make_participant("p1", "Alice", ["engineer"]),
            _make_participant("p2", "Bob", ["creative"]),
        ]
        speaker = _pick_speaker_for_stage(
            participants=participants,
            preferred_tags=["creative"],
            visible_agents=None,
            last_speaker=None,
            fallback_index=0,
        )
        assert speaker == "p2"

    def test_avoids_last_speaker_on_tie(self):
        participants = [
            _make_participant("p1", "Alice", ["creative"]),
            _make_participant("p2", "Bob", ["creative"]),
        ]
        speaker = _pick_speaker_for_stage(
            participants=participants,
            preferred_tags=["creative"],
            visible_agents=None,
            last_speaker="p1",
            fallback_index=0,
        )
        assert speaker == "p2"

    def test_round_robin_fallback(self):
        participants = [
            _make_participant("p1", "Alice", []),
            _make_participant("p2", "Bob", []),
            _make_participant("p3", "Carol", []),
        ]
        # No preferred tags match, falls back to round-robin
        s0 = _pick_speaker_for_stage(
            participants=participants,
            preferred_tags=["finance"],
            visible_agents=None,
            last_speaker=None,
            fallback_index=0,
        )
        s1 = _pick_speaker_for_stage(
            participants=participants,
            preferred_tags=["finance"],
            visible_agents=None,
            last_speaker=None,
            fallback_index=1,
        )
        s2 = _pick_speaker_for_stage(
            participants=participants,
            preferred_tags=["finance"],
            visible_agents=None,
            last_speaker=None,
            fallback_index=2,
        )
        assert s0 == "p1"
        assert s1 == "p2"
        assert s2 == "p3"

    def test_visible_agents_filter(self):
        participants = [
            _make_participant("p1", "Alice", ["creative"]),
            _make_participant("p2", "Bob", ["engineer"]),
            _make_participant("p3", "Carol", ["analyst"]),
        ]
        speaker = _pick_speaker_for_stage(
            participants=participants,
            preferred_tags=["creative"],
            visible_agents=["p2", "p3"],  # p1 excluded
            last_speaker=None,
            fallback_index=0,
        )
        assert speaker in ("p2", "p3")


# ── Checklist heuristics ──────────────────────────────────────────────────


class TestChecklistHeuristics:
    """Tests for _update_checklist() and _is_checklist_complete()."""

    def test_task_planner_default_checklist(self):
        cl = _default_checklist("task_planner_v1")
        assert cl == {
            "gather_requirements": False,
            "draft_plan": False,
            "review": False,
            "finalize": False,
        }

    def test_brainstorm_default_checklist(self):
        cl = _default_checklist("brainstorm_v1")
        assert cl == {"ideate": False, "evaluate": False, "finalize": False}

    def test_draft_and_edit_default_checklist(self):
        cl = _default_checklist("draft_and_edit_v1")
        assert cl == {"outline": False, "draft": False, "edit": False}

    def test_stage_marked_complete(self):
        cl = _default_checklist("task_planner_v1")
        cl = _update_checklist(cl, "gather_requirements")
        assert cl["gather_requirements"] is True
        assert cl["draft_plan"] is False

    def test_all_stages_complete(self):
        cl = _default_checklist("task_planner_v1")
        for stage_id in ("gather_requirements", "draft_plan", "review", "finalize"):
            cl = _update_checklist(cl, stage_id)
        assert _is_checklist_complete(cl) is True

    def test_brainstorm_stage_completion(self):
        cl = _default_checklist("brainstorm_v1")
        for stage_id in ("ideate", "evaluate", "finalize"):
            cl = _update_checklist(cl, stage_id)
        assert _is_checklist_complete(cl) is True

    def test_checklist_incomplete_when_missing(self):
        cl = {"steps": True, "details": False, "summary": True}
        assert _is_checklist_complete(cl) is False

    def test_checklist_complete_when_all_true(self):
        cl = {"steps": True, "details": True, "summary": True}
        assert _is_checklist_complete(cl) is True

    def test_empty_checklist_not_complete(self):
        assert _is_checklist_complete({}) is False


# ── Novelty (Jaccard similarity) ─────────────────────────────────────────


class TestNovelty:
    """Tests for _tok() and _jaccard()."""

    def test_identical_texts(self):
        assert _jaccard("hello world foo bar", "hello world foo bar") == 1.0

    def test_completely_different(self):
        j = _jaccard("alpha beta gamma", "delta epsilon zeta")
        assert j == 0.0

    def test_partial_overlap(self):
        j = _jaccard("cook dinner pasta movie", "cook dinner salad games")
        assert 0.0 < j < 1.0

    def test_stop_words_excluded(self):
        tokens = _tok("the and for with that this from have been were")
        assert len(tokens) == 0

    def test_meaningful_words_kept(self):
        tokens = _tok("restaurant dinner movie budget planning")
        assert "restaurant" in tokens
        assert "dinner" in tokens
        assert "movie" in tokens

    def test_empty_text(self):
        assert _jaccard("", "") == 1.0
        assert _jaccard("hello", "") == 0.0
        assert _jaccard("", "hello") == 0.0


# ── Safe fallback ────────────────────────────────────────────────────────


class TestSafeFallback:
    """Tests for _safe_fallback()."""

    def test_fallback_is_natural_text(self):
        fb = _safe_fallback("task_planner_v1", topic="making cheesecake")
        assert isinstance(fb, str)
        assert len(fb) > 20
        # No section headers in natural fallback
        assert "STEPS:" not in fb
        assert "DETAILS:" not in fb

    def test_fallback_without_topic(self):
        fb = _safe_fallback("task_planner_v1")
        assert isinstance(fb, str)
        assert len(fb) > 20

    def test_unknown_profile_returns_generic(self):
        fb = _safe_fallback("unknown_profile_xyz")
        assert isinstance(fb, str)
        assert len(fb) > 0


# ── ensure_defaults engine key ────────────────────────────────────────────


class TestEnsureDefaultsEngine:
    """Tests that ensure_defaults sets engine=native."""

    def test_engine_default_is_native(self):
        room = {"policy": {}}
        ensure_defaults(room)
        assert room["policy"]["engine"] == "native"

    def test_engine_not_overwritten_if_set(self):
        room = {"policy": {"engine": "crew"}}
        ensure_defaults(room)
        assert room["policy"]["engine"] == "crew"


# ── run_crew_turn integration ─────────────────────────────────────────────


class TestRunCrewTurnIntegration:
    """Integration tests for run_crew_turn() with mocked LLM + storage."""

    def _valid_llm_output(self):
        return (
            "STEPS:\n1) Cook pasta at home\n2) Watch a movie on Netflix\n\n"
            "DETAILS:\n- Pasta: €8\n- Netflix: €0\n- Total: €8\n\n"
            "SUMMARY:\nCozy pasta and movie night!"
        )

    def _patches(self, room, proj_map, participants, llm_return=None, llm_side_effect=None):
        """Build a set of patch.object contexts for run_crew_turn."""
        m_rooms = _crew_engine_mod.rooms
        m_projects = _crew_engine_mod.projects

        mock_llm = AsyncMock()
        if llm_side_effect:
            mock_llm.side_effect = llm_side_effect
        elif llm_return is not None:
            mock_llm.return_value = llm_return
        else:
            mock_llm.return_value = self._valid_llm_output()

        patches = [
            patch.object(m_rooms, "get_room", side_effect=lambda rid: room),
            patch.object(m_rooms, "update_room", side_effect=lambda rid, u: room.update(u) or room),
            patch.object(m_projects, "get_project_by_id", side_effect=lambda pid: proj_map.get(pid)),
            patch.object(_crew_engine_mod, "resolve_participants", return_value=participants),
            patch.object(_crew_engine_mod, "llm_text", mock_llm),
            patch.object(_crew_engine_mod, "build_persona_prompt", return_value="You are a persona."),
            patch.object(_crew_engine_mod, "build_chat_messages", return_value=[{"role": "system", "content": "test"}]),
            patch.object(_crew_engine_mod, "_recent_conversation_query", return_value="test query"),
        ]
        return patches, mock_llm

    def _std_fixtures(self):
        room = _make_room()
        proj_map = {
            "persona-a": _make_project("persona-a", "Alice"),
            "persona-b": _make_project("persona-b", "Bob"),
        }
        participants = [
            _make_participant("persona-a", "Alice", ["romantic", "support"]),
            _make_participant("persona-b", "Bob", ["creative"]),
        ]
        return room, proj_map, participants

    @pytest.mark.asyncio
    async def test_crew_turn_basic(self):
        """Full run_crew_turn with mocked rooms + projects + LLM."""
        room, proj_map, participants = self._std_fixtures()
        patches, _ = self._patches(room, proj_map, participants)

        ctx_managers = [p.start() for p in patches]
        try:
            result = await run_crew_turn(room_id="room-crew-1")
        finally:
            for p in patches:
                p.stop()

        assert "new_messages" in result
        assert len(result["new_messages"]) == 1
        assert "speakers" in result
        assert len(result["speakers"]) == 1
        assert "engine_debug" in result
        assert result["engine_debug"]["engine"] == "crew"
        assert result["engine_debug"]["profile_id"] == "task_planner_v1"
        assert result["engine_debug"]["stage"] == "gather_requirements"

    @pytest.mark.asyncio
    async def test_crew_turn_advances_stage(self):
        """After a successful turn, stage_index should advance."""
        room, proj_map, participants = self._std_fixtures()
        patches, _ = self._patches(room, proj_map, participants)

        ctx = [p.start() for p in patches]
        try:
            result = await run_crew_turn(room_id="room-crew-1")
        finally:
            for p in patches:
                p.stop()

        crew_state = room.get("state", {}).get("crew", {})
        assert crew_state.get("stage_index") == 1
        assert crew_state.get("current_stage") == "draft_plan"

    @pytest.mark.asyncio
    async def test_crew_turn_natural_text_accepted(self):
        """Natural conversational text passes validation without sections."""
        room, proj_map, participants = self._std_fixtures()
        natural_text = (
            "I think we should start with a simple recipe. "
            "We need cream cheese, sugar, eggs, and vanilla extract. "
            "The key is to let everything come to room temperature first."
        )
        patches, _ = self._patches(room, proj_map, participants, llm_return=natural_text)

        ctx = [p.start() for p in patches]
        try:
            result = await run_crew_turn(room_id="room-crew-1")
        finally:
            for p in patches:
                p.stop()

        assert result["engine_debug"]["validation"]["ok"] is True
        assert result["new_messages"][0]["content"] == natural_text

    @pytest.mark.asyncio
    async def test_crew_turn_fallback_on_short_output(self):
        """Too-short output triggers natural fallback (no section headers)."""
        room, proj_map, participants = self._std_fixtures()
        patches, _ = self._patches(
            room, proj_map, participants,
            llm_return="OK sure.",
        )

        ctx = [p.start() for p in patches]
        try:
            result = await run_crew_turn(room_id="room-crew-1")
        finally:
            for p in patches:
                p.stop()

        msg_content = result["new_messages"][0]["content"]
        # Fallback is natural text, no section headers
        assert "STEPS:" not in msg_content
        assert len(msg_content) > 20
        assert result["engine_debug"]["validation"]["ok"] is False

    @pytest.mark.asyncio
    async def test_crew_turn_budget_extraction_from_topic(self):
        """Budget limit is extracted from topic text when not set in policy."""
        room = _make_room(
            topic="Plan a date night under €25",
            policy={"engine": "crew", "crew": {"profile_id": "task_planner_v1"}},
        )
        proj_map = {
            "persona-a": _make_project("persona-a", "Alice"),
            "persona-b": _make_project("persona-b", "Bob"),
        }
        participants = [
            _make_participant("persona-a", "Alice", ["romantic"]),
            _make_participant("persona-b", "Bob", ["creative"]),
        ]
        patches, _ = self._patches(
            room, proj_map, participants,
            llm_return=(
                "STEPS:\n1) Fancy dinner\n\n"
                "DETAILS:\n- Dinner: €50\n- Total: €50\n\n"
                "SUMMARY:\nLet's eat!"
            ),
        )

        ctx = [p.start() for p in patches]
        try:
            result = await run_crew_turn(room_id="room-crew-1")
        finally:
            for p in patches:
                p.stop()

        # Budget over €25 limit extracted from topic, so validation fails
        # and fallback is used
        msg_content = result["new_messages"][0]["content"]
        assert "STEPS:" in msg_content

    @pytest.mark.asyncio
    async def test_crew_turn_room_not_found(self):
        """Raises ValueError if room doesn't exist."""
        with patch.object(_crew_engine_mod.rooms, "get_room", return_value=None):
            with pytest.raises(ValueError, match="Room not found"):
                await run_crew_turn(room_id="nonexistent")

    @pytest.mark.asyncio
    async def test_crew_turn_no_participants(self):
        """Raises ValueError if no valid participants."""
        room = _make_room()
        with patch.object(_crew_engine_mod.rooms, "get_room", return_value=room), \
             patch.object(_crew_engine_mod, "resolve_participants", return_value=[]):
            with pytest.raises(ValueError, match="No valid participants"):
                await run_crew_turn(room_id="room-crew-1")

    @pytest.mark.asyncio
    async def test_crew_turn_unknown_profile(self):
        """Raises ValueError for unknown profile."""
        room = _make_room(
            policy={"engine": "crew", "crew": {"profile_id": "nonexistent_profile"}},
        )
        with patch.object(_crew_engine_mod.rooms, "get_room", return_value=room), \
             patch.object(_crew_engine_mod, "resolve_participants", return_value=[
                 _make_participant("persona-a", "Alice", []),
             ]):
            with pytest.raises(ValueError, match="Unknown workflow profile"):
                await run_crew_turn(room_id="room-crew-1")

    @pytest.mark.asyncio
    async def test_crew_turn_message_appended(self):
        """The generated message is appended to room.messages."""
        room, proj_map, participants = self._std_fixtures()
        original_msg_count = len(room["messages"])
        patches, _ = self._patches(room, proj_map, participants)

        ctx = [p.start() for p in patches]
        try:
            await run_crew_turn(room_id="room-crew-1")
        finally:
            for p in patches:
                p.stop()

        assert len(room["messages"]) == original_msg_count + 1
        assert room["messages"][-1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_crew_turn_state_persisted(self):
        """Crew state is persisted to room.state.crew."""
        room, proj_map, participants = self._std_fixtures()
        patches, _ = self._patches(room, proj_map, participants)

        ctx = [p.start() for p in patches]
        try:
            await run_crew_turn(room_id="room-crew-1")
        finally:
            for p in patches:
                p.stop()

        crew_state = room.get("state", {}).get("crew", {})
        assert crew_state.get("run_id") is not None
        assert crew_state.get("current_stage") is not None
        assert "checklist" in crew_state
        assert "progress" in crew_state


# ── Dispatch wiring (routes/play_mode imports don't crash) ────────────────


class TestDispatchWiring:
    """Tests that the additive dispatch wiring doesn't break native paths."""

    def test_ensure_defaults_engine_native(self):
        """Default engine is 'native', not 'crew'."""
        room = {"policy": {}}
        ensure_defaults(room)
        assert room["policy"]["engine"] == "native"

    def test_ensure_defaults_preserves_crew(self):
        """If engine is already 'crew', ensure_defaults doesn't overwrite."""
        room = {"policy": {"engine": "crew"}}
        ensure_defaults(room)
        assert room["policy"]["engine"] == "crew"

    def test_crew_engine_import(self):
        """crew_engine module imports cleanly."""
        from app.teams.crew_engine import run_crew_turn
        assert callable(run_crew_turn)

    def test_crew_profiles_import(self):
        """crew_profiles module imports cleanly."""
        from app.teams.crew_profiles import get_profile, list_profiles
        assert callable(get_profile)
        assert callable(list_profiles)

    def test_routes_import(self):
        """routes module imports cleanly (includes crew_engine import)."""
        from app.teams.routes import router
        assert router is not None

    def test_play_mode_import(self):
        """play_mode module imports cleanly (includes crew_engine import)."""
        from app.teams.play_mode import start_play_mode
        assert callable(start_play_mode)
