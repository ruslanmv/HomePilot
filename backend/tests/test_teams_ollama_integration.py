# backend/tests/test_teams_ollama_integration.py
"""
Integration test for Teams multi-agent workflow using a real Ollama LLM.

Purpose:
  - Validates the full end-to-end flow: create room → add personas → send
    message → run orchestrator step → verify persona responses.
  - Checks that agenda/topic/description from the wizard are wired through
    to the persona prompt context.
  - Validates identity rules: no reasoning leaks, no speaker labels, no
    identity drift, proper in-character responses.

Requirements:
  - Local Ollama server running on 127.0.0.1:11434
  - At least one small model pulled (e.g. llama3.2:3b, llama3:8b)
  - NOT designed for CI/GitHub Actions — only for local testing.

Skip behavior:
  - If Ollama is unreachable, all tests are automatically skipped.
  - If no suitable model is found, all tests are automatically skipped.
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
        # Preference order
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

def _make_persona_project(name: str, role: str, description: str) -> Dict[str, Any]:
    """Create a minimal persona project dict for testing."""
    pid = str(uuid.uuid4())
    return {
        "id": pid,
        "name": name,
        "description": description,
        "project_type": "persona",
        "persona_agent": {
            "label": name,
            "role": role,
            "persona_class": role,
            "system_prompt": (
                f"You are {name}, a {role}. {description} "
                "Keep responses under 2 sentences for testing."
            ),
            "response_style": {"tone": "casual"},
        },
        "instructions": "",
    }


def _make_room(
    name: str,
    description: str,
    participant_ids: List[str],
    agenda: List[str] | None = None,
    topic: str | None = None,
    turn_mode: str = "reactive",
) -> Dict[str, Any]:
    """Create a room dict with wizard-like params (simulates CreateSessionWizard)."""
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "description": description,
        "topic": topic or description,  # Wizard fix: description → topic
        "participant_ids": participant_ids,
        "turn_mode": turn_mode,
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
    }


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def personas() -> List[Dict[str, Any]]:
    return [
        _make_persona_project(
            "Girlfriend",
            "romantic companion",
            "A caring and playful girlfriend who loves planning fun activities.",
        ),
        _make_persona_project(
            "Partner",
            "romantic companion",
            "A thoughtful and detail-oriented partner who focuses on logistics.",
        ),
    ]


@pytest.fixture(scope="module")
def event_loop():
    """Create a module-scoped event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Tests ───────────────────────────────────────────────────────────────────

@skip_no_ollama
class TestOllamaTeamsFlow:
    """End-to-end test: wizard → room → message → persona responses."""

    def test_ollama_model_info(self):
        """Print which model we're using (diagnostic)."""
        print(f"\n  Ollama model: {OLLAMA_MODEL}")
        assert OLLAMA_MODEL is not None

    @pytest.mark.asyncio
    async def test_full_reactive_flow(self, personas):
        """Test the full reactive flow: send message → personas respond."""
        from app.teams import rooms as rooms_mod
        from app.teams.meeting_engine import (
            build_persona_prompt,
            build_chat_messages,
        )
        from app.teams.orchestrator import (
            run_reactive_step,
            ensure_defaults,
        )
        from app.teams.participants_resolver import infer_role_tags

        persona_gf = personas[0]
        persona_pt = personas[1]

        # 1. Create room (simulates wizard → backend)
        room = _make_room(
            name="Date Night Planning Test",
            description="Planning a fun date night together",
            participant_ids=[persona_gf["id"], persona_pt["id"]],
            agenda=["Pick a restaurant", "Decide on activity", "Set a time"],
            topic="Planning a fun date night together",
            turn_mode="reactive",
        )

        # Persist room
        rooms_mod._ensure_dir()
        rooms_mod._write(room)
        room_id = room["id"]

        try:
            # 2. Verify room was created with topic and agenda
            stored = rooms_mod.get_room(room_id)
            assert stored is not None
            assert stored["topic"] == "Planning a fun date night together"
            assert stored["agenda"] == ["Pick a restaurant", "Decide on activity", "Set a time"]
            assert stored["description"] == "Planning a fun date night together"

            # 3. Add human message
            room = rooms_mod.add_message(
                room_id=room_id,
                sender_id="human",
                sender_name="You",
                content="Hey everyone! Let's plan our date night. What restaurant should we go to?",
                role="user",
            )
            assert room is not None
            assert len(room["messages"]) == 1

            # 4. Verify persona prompt includes topic and agenda
            others = [persona_pt]
            prompt = build_persona_prompt(persona_gf, room, others, knowledge_query="")
            assert "Planning a fun date night together" in prompt
            assert "Pick a restaurant" in prompt
            assert "Decide on activity" in prompt
            assert "Set a time" in prompt
            assert f'You are "Girlfriend"' in prompt

            # 5. Build generate_fn using real Ollama
            model = OLLAMA_MODEL

            async def generate_fn(pid: str, room_state: Dict[str, Any]) -> str:
                proj = persona_gf if pid == persona_gf["id"] else persona_pt
                all_projects = [persona_gf, persona_pt]
                others_for = [p for p in all_projects if p.get("id") != pid]
                system_prompt = build_persona_prompt(
                    proj, room_state, others_for, knowledge_query="",
                )
                chat_messages = build_chat_messages(
                    room_state, system_prompt, current_persona_id=pid,
                )
                # Direct Ollama HTTP call
                import httpx
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(
                        "http://127.0.0.1:11434/v1/chat/completions",
                        json={
                            "model": model,
                            "messages": chat_messages,
                            "temperature": 0.7,
                            "max_tokens": 200,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    return content.strip()

            # 6. Build participants for orchestrator
            participants = [
                {
                    "persona_id": persona_gf["id"],
                    "display_name": "Girlfriend",
                    "role_tags": infer_role_tags(persona_gf),
                },
                {
                    "persona_id": persona_pt["id"],
                    "display_name": "Partner",
                    "role_tags": infer_role_tags(persona_pt),
                },
            ]

            # 7. Run reactive step
            result = await run_reactive_step(
                room_id,
                last_human_message="Hey everyone! Let's plan our date night. What restaurant should we go to?",
                participants=participants,
                generate_fn=generate_fn,
            )

            # 8. Verify results
            updated_room = result["room"]
            new_messages = result["new_messages"]
            speakers = result["speakers"]

            print(f"\n  Speakers: {speakers}")
            print(f"  New messages: {len(new_messages)}")
            for msg in new_messages:
                print(f"    [{msg['sender_name']}]: {msg['content'][:100]}...")

            # At least one persona should have responded
            assert len(new_messages) >= 1, "Expected at least one persona response"
            assert len(speakers) >= 1, "Expected at least one speaker"

            # Verify response quality
            for msg in new_messages:
                content = msg["content"]
                sender = msg["sender_name"]

                # No empty responses
                assert len(content) > 5, f"{sender}'s response is too short: {content!r}"

                # No reasoning leaks (thinking tags)
                assert "<think" not in content.lower(), f"Reasoning leak in {sender}: {content[:80]}"
                assert "</think" not in content.lower(), f"Reasoning leak in {sender}: {content[:80]}"

                # No speaker labels in output (the UI labels speakers)
                assert not re.match(r"^(Girlfriend|Partner|You):\s", content), \
                    f"Speaker label in {sender}: {content[:80]}"

                # No identity drift (shouldn't mention being an AI/assistant)
                lower = content.lower()
                assert "as an ai" not in lower, f"Identity drift in {sender}: {content[:80]}"
                assert "language model" not in lower, f"Identity drift in {sender}: {content[:80]}"

        finally:
            # Cleanup
            rooms_mod.delete_room(room_id)

    @pytest.mark.asyncio
    async def test_full_initiative_flow(self, personas):
        """Test the BG3-style initiative flow: round-robin queue rotation."""
        from app.teams import rooms as rooms_mod
        from app.teams.meeting_engine import (
            build_persona_prompt,
            build_chat_messages,
        )
        from app.teams.orchestrator import (
            run_initiative_step,
            ensure_defaults,
        )
        from app.teams.participants_resolver import infer_role_tags

        persona_gf = personas[0]
        persona_pt = personas[1]

        room = _make_room(
            name="Initiative Mode Test",
            description="Testing round-robin turn order",
            participant_ids=[persona_gf["id"], persona_pt["id"]],
            agenda=["Topic A", "Topic B"],
            turn_mode="round-robin",
        )

        rooms_mod._ensure_dir()
        rooms_mod._write(room)
        room_id = room["id"]

        try:
            # Add a human message for context
            rooms_mod.add_message(
                room_id=room_id,
                sender_id="human",
                sender_name="You",
                content="What do you think about going to a sushi restaurant?",
                role="user",
            )

            model = OLLAMA_MODEL

            async def generate_fn(pid: str, room_state: Dict[str, Any]) -> str:
                proj = persona_gf if pid == persona_gf["id"] else persona_pt
                all_projects = [persona_gf, persona_pt]
                others_for = [p for p in all_projects if p.get("id") != pid]
                system_prompt = build_persona_prompt(
                    proj, room_state, others_for, knowledge_query="",
                )
                chat_messages = build_chat_messages(
                    room_state, system_prompt, current_persona_id=pid,
                )
                import httpx
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(
                        "http://127.0.0.1:11434/v1/chat/completions",
                        json={
                            "model": model,
                            "messages": chat_messages,
                            "temperature": 0.7,
                            "max_tokens": 200,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return data["choices"][0]["message"]["content"].strip()

            participants = [
                {
                    "persona_id": persona_gf["id"],
                    "display_name": "Girlfriend",
                    "role_tags": infer_role_tags(persona_gf),
                },
                {
                    "persona_id": persona_pt["id"],
                    "display_name": "Partner",
                    "role_tags": infer_role_tags(persona_pt),
                },
            ]

            # Round 1: run_initiative_step increments round to 1 before selecting.
            # queue_idx = 1 % 2 = 1 → picks Partner (index 1)
            result1 = await run_initiative_step(
                room_id,
                participants=participants,
                generate_fn=generate_fn,
            )

            speakers1 = result1["speakers"]
            print(f"\n  Initiative Round 1 speakers: {speakers1}")
            assert len(speakers1) == 1, "Initiative should pick exactly 1 speaker"

            # Round 2: round incremented to 2. queue_idx = 2 % 2 = 0 → picks Girlfriend (index 0)
            result2 = await run_initiative_step(
                room_id,
                participants=participants,
                generate_fn=generate_fn,
            )

            speakers2 = result2["speakers"]
            print(f"  Initiative Round 2 speakers: {speakers2}")
            assert len(speakers2) == 1, "Initiative should pick exactly 1 speaker"

            # The two rounds should pick DIFFERENT speakers (round-robin rotation)
            assert speakers1[0] != speakers2[0], "Round-robin should alternate speakers"

            # Verify messages
            final_room = rooms_mod.get_room(room_id)
            assert final_room is not None
            persona_msgs = [m for m in final_room["messages"] if m["role"] == "assistant"]
            assert len(persona_msgs) == 2, f"Expected 2 persona messages, got {len(persona_msgs)}"

            for msg in persona_msgs:
                print(f"    [{msg['sender_name']}]: {msg['content'][:100]}...")
                assert len(msg["content"]) > 5

        finally:
            rooms_mod.delete_room(room_id)

    @pytest.mark.asyncio
    async def test_wizard_data_persists(self, personas):
        """Verify that wizard data (name, description, topic, agenda) persists
        correctly through the room lifecycle."""
        from app.teams import rooms as rooms_mod

        persona_gf = personas[0]

        # Simulate what happens when CreateSessionWizard calls handleCreate
        room = rooms_mod.create_room(
            name="Date Night Planning",
            description="Planning our perfect evening",
            participant_ids=[persona_gf["id"]],
            turn_mode="reactive",
            agenda=["Pick restaurant", "Choose movie", "Set time"],
            topic=None,  # Wizard doesn't send topic — should default to description
        )
        room_id = room["id"]

        try:
            # Verify topic defaulted to description
            assert room["topic"] == "Planning our perfect evening", \
                f"Topic should default to description, got: {room['topic']!r}"

            # Verify agenda persisted
            assert room["agenda"] == ["Pick restaurant", "Choose movie", "Set time"]

            # Update topic independently
            updated = rooms_mod.update_room(room_id, {"topic": "Sushi dinner and jazz club"})
            assert updated["topic"] == "Sushi dinner and jazz club"
            assert updated["description"] == "Planning our perfect evening"  # unchanged

            # Add agenda item
            new_agenda = updated["agenda"] + ["Plan transportation"]
            updated = rooms_mod.update_room(room_id, {"agenda": new_agenda})
            assert len(updated["agenda"]) == 4
            assert "Plan transportation" in updated["agenda"]

            # Verify persistence (re-read from disk)
            reloaded = rooms_mod.get_room(room_id)
            assert reloaded is not None
            assert reloaded["topic"] == "Sushi dinner and jazz club"
            assert len(reloaded["agenda"]) == 4

        finally:
            rooms_mod.delete_room(room_id)

    @pytest.mark.asyncio
    async def test_topic_in_persona_prompt(self, personas):
        """Verify that topic and agenda appear in the persona system prompt."""
        from app.teams.meeting_engine import build_persona_prompt

        persona_gf = personas[0]
        persona_pt = personas[1]

        room = _make_room(
            name="Prompt Check Room",
            description="Original meeting description",
            participant_ids=[persona_gf["id"], persona_pt["id"]],
            agenda=["Item Alpha", "Item Beta", "Item Gamma"],
            topic="Custom topic different from description",
        )

        prompt = build_persona_prompt(persona_gf, room, [persona_pt])

        # Topic should appear (different from description)
        assert "Custom topic different from description" in prompt
        # Description should appear as meeting purpose
        assert "Original meeting description" in prompt
        # Agenda items should appear
        assert "Item Alpha" in prompt
        assert "Item Beta" in prompt
        assert "Item Gamma" in prompt
        # Meeting name
        assert "Prompt Check Room" in prompt

    @pytest.mark.asyncio
    async def test_topic_same_as_description_no_duplication(self, personas):
        """When topic == description, prompt shouldn't repeat it."""
        from app.teams.meeting_engine import build_persona_prompt

        persona_gf = personas[0]
        persona_pt = personas[1]

        room = _make_room(
            name="No Dup Room",
            description="Date planning",
            participant_ids=[persona_gf["id"], persona_pt["id"]],
            topic="Date planning",  # Same as description
        )

        prompt = build_persona_prompt(persona_gf, room, [persona_pt])
        # "Date planning" should appear exactly once (as meeting purpose)
        count = prompt.count("Date planning")
        assert count == 1, f"Expected 'Date planning' once, found {count} times"
