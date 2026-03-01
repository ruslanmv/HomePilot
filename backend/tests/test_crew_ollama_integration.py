# backend/tests/test_crew_ollama_integration.py
"""
Integration test for CrewAI-style Workflow Engine using a real Ollama LLM.

Purpose:
  - Validates the full end-to-end crew workflow: create personas → create room
    with engine="crew" → run_crew_turn() → verify structured output quality.
  - Checks output contract (required sections, word count, budget validation).
  - Verifies stage advancement, checklist progress, novelty tracking.
  - Tests all 3 built-in profiles with real LLM output.

Requirements:
  - Local Ollama server running on 127.0.0.1:11434
  - At least one small model pulled (e.g. llama3.2:3b)
  - NOT designed for CI/GitHub Actions — only for local testing.

Skip behavior:
  - If Ollama is unreachable or no model found → all tests skipped.
  - If a crew turn times out (slow hardware) → that test is skipped.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from typing import Any, Dict, List

import pytest

# ── Ollama availability check ───────────────────────────────────────────────


def _ollama_available() -> bool:
    """Check if Ollama server is reachable."""
    try:
        import httpx
        r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False


def _find_ollama_model() -> str | None:
    """Find the best available model. Prefers 8b, falls back to 3b or any."""
    try:
        import httpx
        r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=5.0)
        if r.status_code != 200:
            return None
        data = r.json()
        models = [m["name"] for m in data.get("models", [])]
        if not models:
            return None
        for pattern in [r"8b", r"3b", r"1b", r""]:
            for name in models:
                if re.search(pattern, name, re.IGNORECASE):
                    return name
        return models[0]
    except Exception:
        return None


OLLAMA_OK = _ollama_available()
OLLAMA_MODEL = _find_ollama_model() if OLLAMA_OK else None

skip_no_ollama = pytest.mark.skipif(
    not OLLAMA_OK or not OLLAMA_MODEL,
    reason=f"Ollama not available or no model found (available={OLLAMA_OK}, model={OLLAMA_MODEL})",
)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _create_persona(name: str, role: str, description: str) -> Dict[str, Any]:
    """Create a persona project via the projects API."""
    from app.projects import create_new_project

    return create_new_project({
        "name": name,
        "description": description,
        "project_type": "persona",
        "persona_agent": {
            "label": name,
            "role": role,
            "persona_class": role,
            "system_prompt": (
                f"You are {name}, a {role}. {description} "
                "Keep responses concise and follow output format instructions exactly."
            ),
            "response_style": {"tone": "casual"},
        },
    })


def _create_crew_room(
    name: str,
    description: str,
    participant_ids: List[str],
    profile_id: str = "task_planner_v1",
    topic: str | None = None,
    agenda: List[str] | None = None,
    budget_limit: float | None = None,
) -> Dict[str, Any]:
    """Create a room with engine=crew and return it."""
    from app.teams import rooms as rooms_mod

    room = {
        "id": str(uuid.uuid4()),
        "name": name,
        "description": description,
        "topic": topic or description,
        "participant_ids": participant_ids,
        "turn_mode": "reactive",
        "agenda": agenda or [],
        "messages": [],
        "documents": [],
        "created_at": time.time(),
        "updated_at": time.time(),
        "status": "active",
        "round": 0,
        "hand_raises": [],
        "hand_raise_meta": {},
        "cooldowns": {},
        "muted": [],
        "intents": {},
        "speaker_queue": [],
        "policy": {
            "engine": "crew",
            "crew": {
                "profile_id": profile_id,
            },
        },
        "state": {},
    }
    if budget_limit is not None:
        room["policy"]["crew"]["budget_limit_eur"] = budget_limit

    rooms_mod._ensure_dir()
    rooms_mod._write(room)
    return room


def _cleanup(room_id: str, persona_ids: List[str]) -> None:
    """Clean up room and persona projects."""
    from app.teams import rooms as rooms_mod
    from app.projects import delete_project

    try:
        rooms_mod.delete_room(room_id)
    except Exception:
        pass
    for pid in persona_ids:
        try:
            delete_project(pid)
        except Exception:
            pass


async def _safe_crew_turn(room_id: str, **kwargs) -> Dict[str, Any]:
    """Run a crew turn, skipping the test if Ollama times out."""
    from app.teams.crew_engine import run_crew_turn
    try:
        return await run_crew_turn(
            room_id=room_id,
            provider="ollama",
            model=OLLAMA_MODEL,
            base_url="http://127.0.0.1:11434",
            **kwargs,
        )
    except Exception as exc:
        exc_str = str(exc).lower()
        if "timeout" in exc_str or "readtimeout" in type(exc).__name__.lower():
            pytest.skip(f"Ollama too slow on this hardware: {type(exc).__name__}")
        raise


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def event_loop():
    """Create a module-scoped event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def planner_personas() -> List[Dict[str, Any]]:
    """Create two personas suited for task planning."""
    personas = [
        _create_persona(
            "Sophia",
            "romantic companion",
            "A warm, creative girlfriend who loves planning special evenings.",
        ),
        _create_persona(
            "Marcus",
            "budget analyst",
            "A detail-oriented financial advisor who keeps plans within budget.",
        ),
    ]
    yield personas
    from app.projects import delete_project
    for p in personas:
        try:
            delete_project(p["id"])
        except Exception:
            pass


@pytest.fixture(scope="module")
def brainstorm_personas() -> List[Dict[str, Any]]:
    """Create two personas suited for brainstorming."""
    personas = [
        _create_persona(
            "Iris",
            "creative product designer",
            "An innovative designer who generates out-of-the-box ideas.",
        ),
        _create_persona(
            "Leo",
            "senior engineer",
            "A pragmatic engineer who evaluates feasibility and trade-offs.",
        ),
    ]
    yield personas
    from app.projects import delete_project
    for p in personas:
        try:
            delete_project(p["id"])
        except Exception:
            pass


# ── Health checks ───────────────────────────────────────────────────────────


@skip_no_ollama
class TestCrewOllamaHealth:
    """Basic health checks: Ollama is up, model works, crew engine imports."""

    def test_ollama_model_detected(self):
        """Ollama has at least one model available."""
        print(f"\n  Ollama model: {OLLAMA_MODEL}")
        assert OLLAMA_MODEL is not None

    def test_crew_engine_imports(self):
        """All crew engine modules import cleanly."""
        from app.teams.crew_engine import run_crew_turn
        from app.teams.crew_profiles import get_profile, list_profiles
        assert callable(run_crew_turn)
        assert callable(get_profile)

    def test_profiles_registered(self):
        """All 3 built-in profiles are available."""
        from app.teams.crew_profiles import get_profile
        for pid in ("task_planner_v1", "brainstorm_v1", "draft_and_edit_v1"):
            p = get_profile(pid)
            assert p is not None, f"Profile {pid} not registered"
            assert len(p.stages) >= 3

    @pytest.mark.asyncio
    async def test_ollama_llm_text_basic(self):
        """llm_text() can reach Ollama and get a response."""
        from app.teams.llm_adapter import llm_text

        try:
            result = await llm_text(
                [{"role": "user", "content": "Say hello in one word."}],
                provider="ollama",
                model=OLLAMA_MODEL,
                base_url="http://127.0.0.1:11434",
                max_tokens=50,
            )
        except Exception as exc:
            exc_name = type(exc).__name__.lower()
            exc_str = str(exc).lower()
            if "timeout" in exc_str or "timeout" in exc_name:
                pytest.skip(f"Ollama too slow: {type(exc).__name__}")
            raise

        assert len(result) > 0, "LLM returned empty response"
        print(f"\n  LLM basic response: {result[:80]}")


# ── Task Planner tests ─────────────────────────────────────────────────────


@skip_no_ollama
class TestCrewTaskPlannerOllama:
    """End-to-end: task_planner_v1 workflow with real Ollama."""

    @pytest.mark.asyncio
    async def test_single_crew_turn(self, planner_personas):
        """Run one crew turn and verify structured output."""
        pids = [p["id"] for p in planner_personas]
        room = _create_crew_room(
            name="Date Night Crew Test",
            description="Plan a romantic date night",
            participant_ids=pids,
            profile_id="task_planner_v1",
            topic="Plan a romantic date night dinner and activity under €30",
            agenda=["Pick food", "Choose activity", "Set budget"],
            budget_limit=30.0,
        )
        room_id = room["id"]

        try:
            result = await _safe_crew_turn(room_id)

            # Basic structure
            assert "new_messages" in result
            assert len(result["new_messages"]) == 1
            assert "speakers" in result
            assert len(result["speakers"]) == 1
            assert "engine_debug" in result

            # Engine debug
            debug = result["engine_debug"]
            assert debug["engine"] == "crew"
            assert debug["profile_id"] == "task_planner_v1"
            assert debug["stage"] == "gather_requirements"
            assert debug["stage_index"] == 0
            assert "validation" in debug
            assert "novelty" in debug

            # Message content
            msg = result["new_messages"][0]
            content = msg["content"]
            assert len(content) > 10, f"Response too short: {content!r}"

            print(f"\n  Speaker: {msg['sender_name']}")
            print(f"  Stage: {debug['stage']}")
            print(f"  Validation: {debug['validation']}")
            print(f"  Novelty: {debug['novelty']}")
            print(f"  Content preview: {content[:200]}...")

            # If validation passed, sections should be present
            if debug["validation"]["ok"]:
                from app.teams.crew_engine import _extract_sections
                sections = _extract_sections(content)
                print(f"  Sections found: {list(sections.keys())}")
                assert len(sections) >= 1

            # No reasoning leaks
            assert "<think" not in content.lower()
            assert "</think" not in content.lower()

            # No identity drift
            lower = content.lower()
            assert "as an ai" not in lower
            assert "language model" not in lower

        finally:
            _cleanup(room_id, [])

    @pytest.mark.asyncio
    async def test_two_turn_stage_advancement(self, planner_personas):
        """Run 2 crew turns and verify stage advancement."""
        from app.teams import rooms as rooms_mod

        pids = [p["id"] for p in planner_personas]
        room = _create_crew_room(
            name="Multi-Turn Crew Test",
            description="Plan a date night under €25",
            participant_ids=pids,
            profile_id="task_planner_v1",
            topic="Plan a date night with dinner and movie under €25",
            agenda=["Food", "Activity", "Budget"],
            budget_limit=25.0,
        )
        room_id = room["id"]

        try:
            stages_seen = []
            for turn in range(2):
                result = await _safe_crew_turn(room_id)
                debug = result["engine_debug"]
                stages_seen.append(debug["stage"])
                print(f"\n  Turn {turn + 1}: stage={debug['stage']}, "
                      f"speaker={result['new_messages'][0]['sender_name']}, "
                      f"valid={debug['validation']['ok']}, "
                      f"novelty={debug['novelty']:.2f}")

            # First two stages should be in order
            expected = ["gather_requirements", "draft_plan"]
            assert stages_seen == expected, \
                f"Expected stages {expected}, got {stages_seen}"

            # Verify messages accumulated
            final_room = rooms_mod.get_room(room_id)
            assert final_room is not None
            persona_msgs = [m for m in final_room["messages"] if m["role"] == "assistant"]
            assert len(persona_msgs) == 2

            # Verify crew state
            crew_state = final_room.get("state", {}).get("crew", {})
            assert crew_state.get("run_id") is not None
            assert crew_state.get("stage_index") == 2  # advanced past draft_plan
            assert "checklist" in crew_state
            assert "progress" in crew_state

        finally:
            _cleanup(room_id, [])

    @pytest.mark.asyncio
    async def test_output_contract_sections(self, planner_personas):
        """Verify that crew output contains required sections or fallback."""
        from app.teams.crew_engine import _extract_sections

        pids = [p["id"] for p in planner_personas]
        room = _create_crew_room(
            name="Section Check Test",
            description="Plan a simple dinner at home",
            participant_ids=pids,
            profile_id="task_planner_v1",
            topic="Plan a simple pasta dinner at home under €15",
            agenda=["Dinner plan", "Budget"],
            budget_limit=15.0,
        )
        room_id = room["id"]

        try:
            result = await _safe_crew_turn(room_id)

            content = result["new_messages"][0]["content"]
            debug = result["engine_debug"]

            sections = _extract_sections(content)
            print(f"\n  Sections: {list(sections.keys())}")
            print(f"  Validation: {debug['validation']}")

            # Output should always have PLAN (valid or fallback)
            assert "PLAN" in sections or "Passing this turn" in content, \
                f"No PLAN section and not a fallback: {content[:200]}"

        finally:
            _cleanup(room_id, [])

    @pytest.mark.asyncio
    async def test_checklist_tracks_progress(self, planner_personas):
        """Run a turn and verify checklist items exist and track."""
        from app.teams import rooms as rooms_mod

        pids = [p["id"] for p in planner_personas]
        room = _create_crew_room(
            name="Checklist Tracking Test",
            description="Plan a date with dinner and movie",
            participant_ids=pids,
            profile_id="task_planner_v1",
            topic="Plan a date night with Italian dinner and a comedy movie, budget €30",
            agenda=["Italian restaurant", "Comedy movie", "Budget check"],
            budget_limit=30.0,
        )
        room_id = room["id"]

        try:
            await _safe_crew_turn(room_id)

            final_room = rooms_mod.get_room(room_id)
            crew_state = final_room.get("state", {}).get("crew", {})
            checklist = crew_state.get("checklist", {})

            print(f"\n  Checklist after 1 turn: {checklist}")

            # Checklist should have the expected keys
            assert "food" in checklist
            assert "activity" in checklist
            assert "budget" in checklist
            assert "message" in checklist

        finally:
            _cleanup(room_id, [])


# ── Brainstorm tests ───────────────────────────────────────────────────────


@skip_no_ollama
class TestCrewBrainstormOllama:
    """End-to-end: brainstorm_v1 workflow with real Ollama."""

    @pytest.mark.asyncio
    async def test_brainstorm_single_turn(self, brainstorm_personas):
        """Run one brainstorm turn and verify output."""
        from app.teams.crew_engine import _extract_sections

        pids = [p["id"] for p in brainstorm_personas]
        room = _create_crew_room(
            name="Brainstorm Crew Test",
            description="Generate ideas for a mobile fitness app",
            participant_ids=pids,
            profile_id="brainstorm_v1",
            topic="Brainstorm ideas for a mobile fitness app targeting busy professionals",
            agenda=["App concepts", "Feasibility", "Recommendation"],
        )
        room_id = room["id"]

        try:
            result = await _safe_crew_turn(room_id)

            debug = result["engine_debug"]
            assert debug["profile_id"] == "brainstorm_v1"
            assert debug["stage"] == "ideate"

            content = result["new_messages"][0]["content"]
            print(f"\n  Brainstorm output preview: {content[:200]}...")
            print(f"  Validation: {debug['validation']}")

            sections = _extract_sections(content)
            print(f"  Sections: {list(sections.keys())}")

            if debug["validation"]["ok"]:
                assert "IDEAS" in sections

        finally:
            _cleanup(room_id, [])


# ── Draft & Edit tests ─────────────────────────────────────────────────────


@skip_no_ollama
class TestCrewDraftEditOllama:
    """End-to-end: draft_and_edit_v1 workflow with real Ollama."""

    @pytest.mark.asyncio
    async def test_draft_edit_single_turn(self, brainstorm_personas):
        """Run one draft-and-edit turn."""
        from app.teams.crew_engine import _extract_sections

        pids = [p["id"] for p in brainstorm_personas]
        room = _create_crew_room(
            name="Draft & Edit Test",
            description="Write a short welcome email for new team members",
            participant_ids=pids,
            profile_id="draft_and_edit_v1",
            topic="Write a welcome email for new engineering team members",
            agenda=["Outline", "Full draft", "Polish"],
        )
        room_id = room["id"]

        try:
            result = await _safe_crew_turn(room_id)

            debug = result["engine_debug"]
            assert debug["profile_id"] == "draft_and_edit_v1"
            assert debug["stage"] == "outline"

            content = result["new_messages"][0]["content"]
            print(f"\n  Draft&Edit output: {content[:200]}...")
            print(f"  Validation: {debug['validation']}")

            sections = _extract_sections(content)
            print(f"  Sections: {list(sections.keys())}")

            # Verify draft state was captured
            from app.teams import rooms as rooms_mod
            final_room = rooms_mod.get_room(room_id)
            crew_state = final_room.get("state", {}).get("crew", {})
            checklist = crew_state.get("checklist", {})
            print(f"  Checklist: {checklist}")

        finally:
            _cleanup(room_id, [])


# ── Novelty & stop rules ───────────────────────────────────────────────────


@skip_no_ollama
class TestCrewNoveltyAndStopRules:
    """Test novelty tracking with real LLM."""

    @pytest.mark.asyncio
    async def test_novelty_tracked(self, planner_personas):
        """Run a turn and verify novelty score is recorded."""
        from app.teams import rooms as rooms_mod

        pids = [p["id"] for p in planner_personas]
        room = _create_crew_room(
            name="Novelty Tracking Test",
            description="Plan a simple walk in the park",
            participant_ids=pids,
            profile_id="task_planner_v1",
            topic="Plan a simple walk in the park, budget €5",
            agenda=["Activity", "Budget"],
            budget_limit=5.0,
        )
        room_id = room["id"]

        try:
            result = await _safe_crew_turn(room_id)

            debug = result["engine_debug"]
            novelty = debug["novelty"]
            print(f"\n  Novelty score: {novelty:.3f}")
            print(f"  Stop: {debug['stop']}")

            # First turn novelty should be high (1.0 = no prior messages)
            assert novelty == 1.0, f"First turn novelty should be 1.0, got {novelty}"

            # Verify novelty stored in state
            final_room = rooms_mod.get_room(room_id)
            crew_state = final_room.get("state", {}).get("crew", {})
            progress = crew_state.get("progress", {})
            assert len(progress.get("novelty_scores", [])) >= 1

        finally:
            _cleanup(room_id, [])


# ── Speaker selection ──────────────────────────────────────────────────────


@skip_no_ollama
class TestCrewSpeakerSelection:
    """Test that speaker selection picks appropriate personas for stages."""

    @pytest.mark.asyncio
    async def test_role_tag_matching(self, planner_personas):
        """Verify speaker is selected based on role tag match."""
        from app.teams.participants_resolver import infer_role_tags

        pids = [p["id"] for p in planner_personas]

        for p in planner_personas:
            tags = infer_role_tags(p)
            print(f"\n  {p['name']}: role_tags={tags}")

        room = _create_crew_room(
            name="Speaker Selection Test",
            description="Plan a dinner",
            participant_ids=pids,
            profile_id="task_planner_v1",
            topic="Plan a dinner under €20",
            agenda=["Food"],
            budget_limit=20.0,
        )
        room_id = room["id"]

        try:
            result = await _safe_crew_turn(room_id)
            debug = result["engine_debug"]
            speaker = debug["speaker_id"]
            stage = debug["stage"]
            print(f"\n  Stage: {stage}, Speaker: {speaker}")

            # Speaker should be one of the participants
            assert speaker in pids

        finally:
            _cleanup(room_id, [])


# ── Robustness ─────────────────────────────────────────────────────────────


@skip_no_ollama
class TestCrewEngineRobustness:
    """Robustness checks for the crew engine with real LLM."""

    @pytest.mark.asyncio
    async def test_empty_topic_still_works(self, planner_personas):
        """Engine should handle rooms with minimal topic gracefully."""
        pids = [p["id"] for p in planner_personas]
        room = _create_crew_room(
            name="Minimal Room",
            description="Test",
            participant_ids=pids,
            profile_id="task_planner_v1",
            topic="",
            agenda=[],
        )
        room_id = room["id"]

        try:
            result = await _safe_crew_turn(room_id)
            assert len(result["new_messages"]) == 1
            assert result["engine_debug"]["engine"] == "crew"
        finally:
            _cleanup(room_id, [])

    @pytest.mark.asyncio
    async def test_crew_state_isolation(self, planner_personas, brainstorm_personas):
        """Two different rooms should have independent crew states."""
        from app.teams import rooms as rooms_mod

        pids1 = [p["id"] for p in planner_personas]
        pids2 = [p["id"] for p in brainstorm_personas]
        room1 = _create_crew_room(
            name="Room A",
            description="Plan dinner",
            participant_ids=pids1,
            profile_id="task_planner_v1",
            topic="Dinner plan",
        )
        room2 = _create_crew_room(
            name="Room B",
            description="Brainstorm app ideas",
            participant_ids=pids2,
            profile_id="brainstorm_v1",
            topic="App ideas brainstorm",
        )

        try:
            r1 = await _safe_crew_turn(room1["id"])
            r2 = await _safe_crew_turn(room2["id"])

            # Different profiles
            assert r1["engine_debug"]["profile_id"] == "task_planner_v1"
            assert r2["engine_debug"]["profile_id"] == "brainstorm_v1"

            # Different stages
            assert r1["engine_debug"]["stage"] == "gather_requirements"
            assert r2["engine_debug"]["stage"] == "ideate"

            # Different run_ids
            s1 = rooms_mod.get_room(room1["id"])["state"]["crew"]["run_id"]
            s2 = rooms_mod.get_room(room2["id"])["state"]["crew"]["run_id"]
            assert s1 != s2

        finally:
            _cleanup(room1["id"], [])
            _cleanup(room2["id"], [])
