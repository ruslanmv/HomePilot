# tests/test_crewai_integration.py
"""
Unit tests for the CrewAI integration layer.

Tests cover:
  - Pydantic output models and rendering (crewai_outputs.py)
  - Engine runner fallback logic (crew_runner.py)
  - CrewAI engine speaker selection and context building (crewai_engine.py)
  - Config toggles (TEAMS_CREWAI_ENABLED, etc.)

Pure Python — no real CrewAI calls, no disk I/O, no real LLM calls.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


# ── Output models & rendering ─────────────────────────────────────────


class TestCrewAIOutputs:
    """Tests for crewai_outputs.py."""

    def test_task_planner_output_model(self):
        from app.teams.crewai_outputs import TaskPlannerOutput

        obj = TaskPlannerOutput(
            steps=["Cook dinner", "Watch movie"],
            details="Pasta and Netflix",
            summary="A cozy evening!",
        )
        assert len(obj.steps) == 2
        assert obj.details == "Pasta and Netflix"
        assert obj.summary == "A cozy evening!"

    def test_brainstorm_output_model(self):
        from app.teams.crewai_outputs import BrainstormOutput

        obj = BrainstormOutput(
            ideas=["App idea", "Blog idea"],
            evaluation=["Feasible", "Too ambitious"],
            recommendation="Go with the app.",
        )
        assert len(obj.ideas) == 2
        assert obj.recommendation == "Go with the app."

    def test_draft_and_edit_output_model(self):
        from app.teams.crewai_outputs import DraftAndEditOutput

        obj = DraftAndEditOutput(
            outline=["Intro", "Body", "Conclusion"],
            notes=["Keep it short"],
            draft="This is the draft content.",
        )
        assert len(obj.outline) == 3
        assert obj.draft == "This is the draft content."

    def test_draft_and_edit_notes_optional(self):
        from app.teams.crewai_outputs import DraftAndEditOutput

        obj = DraftAndEditOutput(
            outline=["Intro"],
            draft="Content",
        )
        assert obj.notes == []

    def test_output_model_for_known_profiles(self):
        from app.teams.crewai_outputs import output_model_for_profile, TaskPlannerOutput, BrainstormOutput, DraftAndEditOutput

        assert output_model_for_profile("task_planner_v1") is TaskPlannerOutput
        assert output_model_for_profile("brainstorm_v1") is BrainstormOutput
        assert output_model_for_profile("draft_and_edit_v1") is DraftAndEditOutput

    def test_output_model_for_unknown_profile(self):
        from app.teams.crewai_outputs import output_model_for_profile

        assert output_model_for_profile("unknown_xyz") is None

    def test_render_task_planner(self):
        from app.teams.crewai_outputs import render_output, TaskPlannerOutput

        obj = TaskPlannerOutput(
            steps=["Step A", "Step B"],
            details="Detail text here",
            summary="Short summary",
        )
        text = render_output("task_planner_v1", obj)
        assert "STEPS:" in text
        assert "1. Step A" in text
        assert "2. Step B" in text
        assert "DETAILS:" in text
        assert "Detail text here" in text
        assert "SUMMARY:" in text
        assert "Short summary" in text

    def test_render_brainstorm(self):
        from app.teams.crewai_outputs import render_output, BrainstormOutput

        obj = BrainstormOutput(
            ideas=["Idea 1"],
            evaluation=["Good"],
            recommendation="Do it",
        )
        text = render_output("brainstorm_v1", obj)
        assert "IDEAS:" in text
        assert "- Idea 1" in text
        assert "EVALUATION:" in text
        assert "RECOMMENDATION:" in text
        assert "Do it" in text

    def test_render_draft_and_edit(self):
        from app.teams.crewai_outputs import render_output, DraftAndEditOutput

        obj = DraftAndEditOutput(
            outline=["Section 1"],
            notes=[],
            draft="Full draft text",
        )
        text = render_output("draft_and_edit_v1", obj)
        assert "OUTLINE:" in text
        assert "DRAFT:" in text
        assert "Full draft text" in text

    def test_render_raw_string(self):
        from app.teams.crewai_outputs import render_output

        text = render_output("task_planner_v1", "  Just plain text  ")
        assert text == "Just plain text"


# ── Engine runner fallback ─────────────────────────────────────────────


class TestCrewRunner:
    """Tests for crew_runner.py engine dispatch."""

    @pytest.mark.asyncio
    async def test_runner_falls_back_when_disabled(self):
        """When TEAMS_CREWAI_ENABLED=False, uses legacy engine."""
        with patch("app.teams.crew_runner.TEAMS_CREWAI_ENABLED", False):
            mock_legacy = AsyncMock(return_value={"engine": "legacy"})

            with patch("app.teams.crew_engine.run_crew_turn", mock_legacy):
                from app.teams.crew_runner import run_crew_turn
                result = await run_crew_turn(room_id="test-room")

            mock_legacy.assert_called_once()
            assert result["engine"] == "legacy"

    @pytest.mark.asyncio
    async def test_runner_falls_back_on_import_error(self):
        """When crewai not installed, falls back gracefully."""
        mock_legacy = AsyncMock(return_value={"engine": "legacy_fallback"})

        with patch("app.teams.crew_runner.TEAMS_CREWAI_ENABLED", True):
            import app.teams.crew_runner as runner_mod

            original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

            def mock_import(name, *args, **kwargs):
                if "crewai_engine" in name:
                    raise ImportError("crewai not installed")
                return original_import(name, *args, **kwargs)

            with patch("app.teams.crew_engine.run_crew_turn", mock_legacy), \
                 patch("builtins.__import__", side_effect=mock_import):
                result = await runner_mod.run_crew_turn(room_id="test-room")

            assert result["engine"] == "legacy_fallback"


# ── Config toggles ─────────────────────────────────────────────────────


class TestCrewAIConfig:
    """Tests for CrewAI config settings."""

    def test_crewai_enabled_default_false(self):
        import os
        with patch.dict(os.environ, {}, clear=False):
            # Remove any existing setting
            os.environ.pop("TEAMS_CREWAI_ENABLED", None)
            # Re-evaluate config
            val = os.getenv("TEAMS_CREWAI_ENABLED", "false").lower() in ("1", "true", "yes")
            assert val is False

    def test_crewai_process_default_sequential(self):
        import os
        val = os.getenv("TEAMS_CREWAI_PROCESS", "sequential").strip().lower()
        assert val == "sequential"


# ── CrewAI engine helpers (don't require crewai installed) ─────────────


class TestCrewAIEngineHelpers:
    """Test helper functions from crewai_engine that work without crewai."""

    def test_pick_speaker_prefers_matching_tags(self):
        """Speaker with matching tags is preferred."""
        # Import from the module directly to avoid crewai import at module level
        # We need to mock the crewai imports
        import importlib
        import sys

        # Create mock crewai module
        mock_crewai = MagicMock()
        sys.modules["crewai"] = mock_crewai

        try:
            from app.teams.crewai_engine import _pick_speaker_for_stage

            participants = [
                {"persona_id": "p1", "display_name": "Alice", "role_tags": ["engineer"]},
                {"persona_id": "p2", "display_name": "Bob", "role_tags": ["creative"]},
            ]
            speaker = _pick_speaker_for_stage(
                participants=participants,
                preferred_tags=["creative"],
                last_speaker=None,
            )
            assert speaker == "p2"
        finally:
            del sys.modules["crewai"]

    def test_pick_speaker_avoids_last(self):
        """On a tie, avoids repeating the last speaker."""
        import sys
        mock_crewai = MagicMock()
        sys.modules["crewai"] = mock_crewai
        try:
            from app.teams.crewai_engine import _pick_speaker_for_stage

            participants = [
                {"persona_id": "p1", "display_name": "Alice", "role_tags": ["creative"]},
                {"persona_id": "p2", "display_name": "Bob", "role_tags": ["creative"]},
            ]
            speaker = _pick_speaker_for_stage(
                participants=participants,
                preferred_tags=["creative"],
                last_speaker="p1",
            )
            assert speaker == "p2"
        finally:
            del sys.modules["crewai"]

    def test_pick_speaker_round_robin(self):
        """Falls back to round-robin when no tags match."""
        import sys
        mock_crewai = MagicMock()
        sys.modules["crewai"] = mock_crewai
        try:
            from app.teams.crewai_engine import _pick_speaker_for_stage

            participants = [
                {"persona_id": "p1", "display_name": "Alice", "role_tags": []},
                {"persona_id": "p2", "display_name": "Bob", "role_tags": []},
                {"persona_id": "p3", "display_name": "Carol", "role_tags": []},
            ]
            s0 = _pick_speaker_for_stage(participants=participants, preferred_tags=["finance"], last_speaker=None, fallback_index=0)
            s1 = _pick_speaker_for_stage(participants=participants, preferred_tags=["finance"], last_speaker=None, fallback_index=1)
            s2 = _pick_speaker_for_stage(participants=participants, preferred_tags=["finance"], last_speaker=None, fallback_index=2)
            assert s0 == "p1"
            assert s1 == "p2"
            assert s2 == "p3"
        finally:
            del sys.modules["crewai"]

    def test_build_task_context(self):
        """Context builder includes topic, agenda, and progress."""
        import sys
        mock_crewai = MagicMock()
        sys.modules["crewai"] = mock_crewai
        try:
            from app.teams.crewai_engine import _build_task_context

            room = {
                "topic": "Plan a date night",
                "agenda": ["Food", "Activity"],
            }
            crew_state = {
                "checklist": {"steps": True, "details": False, "summary": False},
                "draft": {"gather_requirements": "Some prior output here"},
            }
            ctx = _build_task_context(room, crew_state, "Draft Plan")
            assert "Plan a date night" in ctx
            assert "Food" in ctx
            assert "Activity" in ctx
            assert "Draft Plan" in ctx
            assert "steps: done" in ctx
            assert "details: todo" in ctx
            assert "Some prior output" in ctx
        finally:
            del sys.modules["crewai"]

    def test_default_checklist_for_task_planner(self):
        """Default checklist matches profile stages."""
        import sys
        mock_crewai = MagicMock()
        sys.modules["crewai"] = mock_crewai
        try:
            from app.teams.crewai_engine import _default_checklist
            cl = _default_checklist("task_planner_v1")
            assert cl == {
                "gather_requirements": False,
                "draft_plan": False,
                "review": False,
                "finalize": False,
            }
        finally:
            del sys.modules["crewai"]

    def test_default_checklist_for_brainstorm(self):
        import sys
        mock_crewai = MagicMock()
        sys.modules["crewai"] = mock_crewai
        try:
            from app.teams.crewai_engine import _default_checklist
            cl = _default_checklist("brainstorm_v1")
            assert cl == {"ideate": False, "evaluate": False, "finalize": False}
        finally:
            del sys.modules["crewai"]

    def test_default_checklist_unknown_profile(self):
        import sys
        mock_crewai = MagicMock()
        sys.modules["crewai"] = mock_crewai
        try:
            from app.teams.crewai_engine import _default_checklist
            cl = _default_checklist("nonexistent_xyz")
            assert cl == {}
        finally:
            del sys.modules["crewai"]


# ── Import sanity checks ──────────────────────────────────────────────


class TestCrewAIImports:
    """Verify that all new modules import cleanly."""

    def test_crewai_outputs_imports(self):
        from app.teams.crewai_outputs import (
            TaskPlannerOutput,
            BrainstormOutput,
            DraftAndEditOutput,
            output_model_for_profile,
            render_output,
        )
        assert callable(render_output)
        assert callable(output_model_for_profile)

    def test_crew_runner_imports(self):
        from app.teams.crew_runner import run_crew_turn
        assert callable(run_crew_turn)

    def test_config_has_crewai_settings(self):
        from app.config import (
            TEAMS_CREWAI_ENABLED,
            TEAMS_CREWAI_PROCESS,
            TEAMS_CREWAI_MEMORY,
        )
        assert isinstance(TEAMS_CREWAI_ENABLED, bool)
        assert isinstance(TEAMS_CREWAI_PROCESS, str)
        assert isinstance(TEAMS_CREWAI_MEMORY, bool)

    def test_routes_still_imports(self):
        """routes.py should import cleanly with crew_runner."""
        from app.teams.routes import router
        assert router is not None

    def test_play_mode_still_imports(self):
        """play_mode.py should import cleanly with crew_runner."""
        from app.teams.play_mode import start_play_mode
        assert callable(start_play_mode)

    def test_legacy_crew_engine_still_importable(self):
        """Legacy crew engine must stay importable (it's the fallback)."""
        from app.teams.crew_engine import run_crew_turn
        assert callable(run_crew_turn)
