"""avatar_control (B17) — the safety table, and what a tool cannot do.

The batch's three acceptance sentences:

  * an MCP client runs a three-clip sequence on the live avatar — `TestSequence`;
  * capture tools require consent — `TestSafety`, as negative assertions;
  * killing the server changes nothing locally — `TestNothingLocalDepends`, which is a
    claim about *architecture* and is therefore checked by reading what this code can and
    cannot reach, not by killing a process a test runner does not have.
"""

from __future__ import annotations

import json

import pytest

from app.avatar_director import safety
from app.avatar_director.config import AvatarDirectorConfig
from app.avatar_director.control import (
    MAX_SEQUENCE,
    TOOLS,
    AvatarControl,
    ControlError,
    ManifestRegistry,
)
from app.avatar_director.protocol import EMOTE_WHITELIST, ProtocolHandler


def paired(*, consent: bool = False) -> ProtocolHandler:
    handler = ProtocolHandler()
    handler.handle({"v": 1, "type": "hello", "auth": "t", "client": "3dac", "caps": []})
    if consent:
        handler.handle({"v": 1, "type": "user_event", "name": "capture:start"})
    return handler


def bridge(*, sessions=None, registry=None, consent: bool = False):
    handlers = {"a": paired(consent=consent)} if sessions is None else sessions
    control = AvatarControl(sessions=lambda: handlers, registry=registry)
    control.handlers = handlers
    control.session = next(iter(handlers.values())) if handlers else None
    return control


CATALOGUE = ManifestRegistry(
    [
        {
            "id": "bvh_dance_dance_1",
            "description": "A full-bodied dance — hips leading, fast and celebratory.",
            "tags": ["dance", "energetic", "party"],
            "intents": ["dance", "celebrate"],
            "energy": 0.72,
            "stats": {"duration": 22.1},
        },
        {
            "id": "vrma_wave_hello",
            "description": "A small wave, arm only.",
            "tags": ["greeting", "calm"],
            "intents": ["wave"],
            "energy": 0.2,
            "stats": {"duration": 2.4},
        },
        {
            "id": "proc_breathe",
            "description": "Slow breathing, chest and shoulders.",
            "tags": ["calm", "rest"],
            "intents": ["breathe", "idle"],
            "energy": 0.05,
            "stats": {"duration": None},
        },
    ]
)


# ── the three-clip sequence ──────────────────────────────────────────────────


class TestSequence:
    def test_a_three_intent_sequence_reaches_the_live_session_in_order(self):
        control = bridge()
        result = control.invoke(
            "queue_sequence",
            {"intents": [{"intent": "wave"}, {"intent": "dance", "intensity": 0.9}, {"intent": "happy"}]},
        )

        assert result["ok"] is True
        assert result["steps"] == ["wave", "dance", "happy"]
        outbox = control.session.outbox
        assert [m["name"] for m in outbox] == ["wave", "dance", "happy"]
        assert [m["type"] for m in outbox] == ["intent"] * 3
        assert outbox[1]["intensity"] == 0.9

    def test_the_tool_names_intents_and_never_clips(self):
        """§6.14's bridge invariant. A tool that could name a clip would be a second
        animation authority, and the whole point of Tier 1 is that there is one."""
        control = bridge(registry=CATALOGUE)
        control.invoke("play_animation", {"intent": "dance"})

        message = control.session.outbox[0]
        assert message["name"] == "dance"
        assert "clip" not in message and "id" not in message and "file" not in message
        # And the id of a real clip cannot be smuggled through the intent field.
        with pytest.raises(ControlError) as raised:
            control.invoke("play_animation", {"intent": "bvh_dance_dance_1"})
        assert raised.value.code == "not_whitelisted"

    def test_the_intent_source_is_tool_and_never_user(self):
        # §6.5 blocks NSFW for any intent whose source is not the user, and a tool is about
        # as far from the user pressing a button as a source gets.
        control = bridge()
        control.invoke("play_animation", {"intent": "flirt", "intensity": 1})
        assert control.session.outbox[0]["source"] == "tool"

    def test_one_bad_step_refuses_the_whole_sequence(self):
        # A partial performance is harder for a caller to reason about than none.
        control = bridge()
        with pytest.raises(ControlError) as raised:
            control.invoke("queue_sequence", {"intents": [{"intent": "wave"}, {"intent": "twerk"}]})
        assert raised.value.code == "not_whitelisted"
        assert control.session.outbox == []

    def test_a_sequence_is_bounded(self):
        control = bridge()
        long_run = [{"intent": "wave"} for _ in range(MAX_SEQUENCE + 1)]
        with pytest.raises(ControlError) as raised:
            control.invoke("queue_sequence", {"intents": long_run})
        assert raised.value.code == "sequence_too_long"
        assert control.session.outbox == []

    def test_an_empty_sequence_is_a_refusal_not_a_no_op(self):
        control = bridge()
        for payload in ({}, {"intents": []}, {"intents": "wave"}):
            with pytest.raises(ControlError) as raised:
                control.invoke("queue_sequence", payload)
            assert raised.value.code == "bad_args"

    def test_intensity_is_clamped_rather_than_trusted(self):
        control = bridge()
        control.invoke("queue_sequence", {"intents": [{"intent": "wave", "intensity": 40}, {"intent": "sad", "intensity": -3}]})
        assert [m["intensity"] for m in control.session.outbox] == [1.0, 0.0]


# ── the safety table ─────────────────────────────────────────────────────────


class TestSafety:
    def test_the_bridge_implements_exactly_the_tools_with_a_safety_row(self):
        # A tool without a row would run at the default level by accident rather than by
        # decision, and a row without a tool is a promise nothing keeps.
        assert set(TOOLS) == set(safety.TOOL_SAFETY)
        for tool in TOOLS:
            assert hasattr(AvatarControl, f"_{tool}"), tool

    def test_autonomous_tools_need_no_approval(self):
        control = bridge()
        for tool, args in [
            ("play_animation", {"intent": "wave"}),
            ("queue_sequence", {"intents": [{"intent": "wave"}]}),
            ("set_mood", {"valence": 0.4}),
            ("set_scene", {"id": "ocean"}),
        ]:
            assert control.invoke(tool, args)["safety"] == "autonomous", tool

    def test_confirm_tools_refuse_without_an_approval(self):
        control = bridge(consent=True)
        for tool in ("vision_insight", "start_capture", "stop_capture"):
            with pytest.raises(ControlError) as raised:
                control.invoke(tool, {})
            assert raised.value.code == "needs_confirmation", tool

    def test_and_still_refuse_with_an_approval_but_no_client_consent(self):
        """The point of the second gate. A server-side approval is the operator saying yes;
        it is not the user having opted in on the device holding the camera."""
        control = bridge(consent=False)
        for tool in ("vision_insight", "start_capture", "stop_capture"):
            with pytest.raises(ControlError) as raised:
                control.invoke(tool, {}, approved=True)
            assert raised.value.code == "no_client_consent", tool
            assert control.session.outbox == []

    def test_with_both_they_go_through(self):
        control = bridge(consent=True)
        result = control.invoke("start_capture", {"source": "screen"}, approved=True)
        assert result["ok"] is True
        assert result["safety"] == "confirm"

    def test_revoking_consent_mid_session_closes_the_door_again(self):
        control = bridge(consent=True)
        control.invoke("vision_insight", {"prompt": "?"}, approved=True)
        control.session.handle({"v": 1, "type": "user_event", "name": "capture:stop"})
        with pytest.raises(ControlError) as raised:
            control.invoke("vision_insight", {"prompt": "?"}, approved=True)
        assert raised.value.code == "no_client_consent"

    def test_every_tool_the_spec_marks_consent_requiring_is_gated(self):
        for tool in safety.REQUIRES_CLIENT_CONSENT:
            control = bridge(consent=False)
            with pytest.raises(ControlError):
                control.invoke(tool, {}, approved=True)

    def test_an_unknown_tool_is_refused_rather_than_defaulted_through(self):
        control = bridge()
        with pytest.raises(ControlError) as raised:
            control.invoke("delete_everything", {}, approved=True)
        assert raised.value.code == "unknown_tool"

    def test_a_capture_tool_cannot_be_reached_by_spelling_it_differently(self):
        control = bridge(consent=False)
        for name in ("Start_Capture", "start_capture ", "vision_insight\n"):
            with pytest.raises(ControlError) as raised:
                control.invoke(name, {}, approved=True)
            assert raised.value.code == "unknown_tool", name


# ── no live session ──────────────────────────────────────────────────────────


class TestNoSession:
    def test_every_acting_tool_says_so_rather_than_dropping_the_call(self):
        # An MCP client told {"ok": true} while nothing happened has been lied to.
        control = bridge(sessions={})
        for tool, args in [
            ("play_animation", {"intent": "wave"}),
            ("queue_sequence", {"intents": [{"intent": "wave"}]}),
            ("set_mood", {"energy": 0.5}),
            ("set_scene", {"id": "forest"}),
        ]:
            with pytest.raises(ControlError) as raised:
                control.invoke(tool, args)
            assert raised.value.code == "no_session", tool

    def test_an_unauthenticated_socket_is_not_a_session(self):
        # Connected is not paired. Acting on a socket that has not said hello would be
        # acting on whoever happened to open a port.
        control = bridge(sessions={"a": ProtocolHandler()})
        with pytest.raises(ControlError) as raised:
            control.invoke("play_animation", {"intent": "wave"})
        assert raised.value.code == "no_session"

    def test_two_avatars_is_an_error_rather_than_a_guess(self):
        control = bridge(sessions={"a": paired(), "b": paired()})
        with pytest.raises(ControlError) as raised:
            control.invoke("play_animation", {"intent": "wave"})
        assert raised.value.code == "ambiguous_session"

    def test_the_catalogue_tools_work_without_a_session(self):
        # Searching what she *can* do does not require her to be here.
        control = bridge(sessions={}, registry=CATALOGUE)
        assert control.invoke("search_animations", {"query": "dance"})["ok"] is True


# ── the catalogue ────────────────────────────────────────────────────────────


class TestCatalogue:
    def test_search_finds_by_description_tag_and_intent(self):
        control = bridge(registry=CATALOGUE)
        for query, expected in [
            ("celebratory", "bvh_dance_dance_1"),
            ("greeting", "vrma_wave_hello"),
            ("breathe", "proc_breathe"),
        ]:
            results = control.invoke("search_animations", {"query": query})["results"]
            assert results and results[0]["id"] == expected, query

    def test_more_matching_words_rank_higher(self):
        control = bridge(registry=CATALOGUE)
        results = control.invoke("search_animations", {"query": "calm slow breathing"})["results"]
        assert results[0]["id"] == "proc_breathe"

    def test_the_limit_is_bounded_both_ways(self):
        control = bridge(registry=CATALOGUE)
        assert len(control.invoke("search_animations", {"query": "a e i o u", "limit": 99})["results"]) <= 3
        assert len(control.invoke("search_animations", {"query": "calm", "limit": 1})["results"]) == 1

    def test_get_returns_the_record_or_says_it_is_missing(self):
        control = bridge(registry=CATALOGUE)
        assert control.invoke("get_animation", {"id": "proc_breathe"})["animation"]["energy"] == 0.05
        with pytest.raises(ControlError) as raised:
            control.invoke("get_animation", {"id": "nope"})
        assert raised.value.code == "not_found"

    def test_without_a_manifest_the_catalogue_tools_refuse_by_name(self):
        # A search that quietly returned nothing would read as "she can't dance".
        control = bridge(registry=None)
        for tool, args in [("search_animations", {"query": "dance"}), ("get_animation", {"id": "x"})]:
            with pytest.raises(ControlError) as raised:
                control.invoke(tool, args)
            assert raised.value.code == "no_registry", tool

    def test_the_manifest_loader_survives_a_torn_line(self, tmp_path):
        path = tmp_path / "kb.jsonl"
        path.write_text('{"id":"a","tags":["x"]}\n{not json\n{"id":"b","tags":["x"]}\n', encoding="utf-8")
        registry = ManifestRegistry.from_jsonl(str(path))
        assert {r["id"] for r in registry.search("x", limit=9)} == {"a", "b"}

    def test_a_missing_manifest_is_none_rather_than_an_exception(self, tmp_path):
        assert ManifestRegistry.from_jsonl(str(tmp_path / "nope.jsonl")) is None
        assert ManifestRegistry.from_jsonl("") is None


# ── scenes and mood ──────────────────────────────────────────────────────────


class TestSceneAndMood:
    def test_an_unknown_scene_is_refused_rather_than_sent(self):
        control = bridge()
        with pytest.raises(ControlError) as raised:
            control.invoke("set_scene", {"id": "volcano"})
        assert raised.value.code == "unknown_scene"
        assert control.session.outbox == []

    def test_each_shipped_scene_goes_through(self):
        for scene in ("forest", "ocean", "meditation"):
            control = bridge()
            assert control.invoke("set_scene", {"id": scene})["scene"] == scene
            assert control.session.outbox[0] == {"v": 1, "type": "scene", "id": scene}

    def test_mood_is_clamped_to_its_declared_ranges(self):
        control = bridge()
        result = control.invoke("set_mood", {"valence": -9, "energy": 9})
        assert (result["valence"], result["energy"]) == (-1.0, 1.0)

    def test_mood_with_neither_field_is_a_refusal(self):
        control = bridge()
        with pytest.raises(ControlError) as raised:
            control.invoke("set_mood", {"mood": "happy"})
        assert raised.value.code == "bad_args"


# ── killing the server changes nothing ───────────────────────────────────────


class TestNothingLocalDepends:
    """The third acceptance sentence, checked as the architectural claim it is.

    A test runner cannot kill a process and then watch an avatar keep dancing. What it can
    do is establish the property that makes the sentence true: this bridge is a *sender*.
    It holds no animation state, decides nothing about timing, and reaches the avatar only
    by appending a message to a socket's outbox. Everything the avatar does — reflexes,
    selection, blending, scheduling, speech — runs on the device and never asked it
    anything.
    """

    def test_the_bridge_holds_no_avatar_state(self):
        control = bridge(registry=CATALOGUE)
        control.invoke("play_animation", {"intent": "wave"})
        control.invoke("set_mood", {"energy": 0.9})
        control.invoke("set_scene", {"id": "ocean"})

        held = set(vars(control)) - {"handlers", "session"}
        # Counters and its two injected collaborators. No mood, no scene, no current clip.
        assert held == {"_sessions", "registry", "now", "calls", "refusals"}

    def test_it_reaches_the_avatar_only_through_the_outbox(self):
        import inspect

        from app.avatar_director import control as module

        source = inspect.getsource(module.AvatarControl)
        # No socket, no task, no thread: the transport owns all three.
        for forbidden in ("websocket", "send_text", "asyncio", "Thread", "create_task"):
            assert forbidden not in source, forbidden

        # And exactly one method touches the session at all. Counting the word would be a
        # word count; this asks which methods can reach it, which is the actual claim.
        reaching = [
            name
            for name, member in vars(module.AvatarControl).items()
            if callable(member) and "outbox" in inspect.getsource(member)
        ]
        assert reaching == ["_send"]

    def test_it_decides_no_timing(self):
        # The client's scheduler owns crossfades and minimum play times (§6.6). A sequence
        # here is three messages, not three messages and two sleeps.
        import inspect

        from app.avatar_director import control as module

        source = inspect.getsource(module.AvatarControl)
        for forbidden in ("sleep", "delay", "duration", "wait"):
            assert forbidden not in source, forbidden

    def test_the_module_imports_no_transport(self):
        import subprocess
        import sys
        from pathlib import Path

        probe = (
            "import sys; import app.avatar_director.control;"
            "print('fastapi' in sys.modules, 'httpx' in sys.modules,"
            "'app.avatar_director.session' in sys.modules)"
        )
        out = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[2]),
            check=True,
        )
        assert out.stdout.split() == ["False", "False", "False"]

    def test_a_dead_bridge_leaves_the_session_exactly_as_it_was(self):
        # The nearest a unit test gets to pulling the plug: the session's own state is
        # untouched by everything the bridge did, because the bridge only ever appended.
        control = bridge(consent=True)
        session = control.session
        before = dict(vars(session.state))

        control.invoke("play_animation", {"intent": "wave"})
        control.invoke("queue_sequence", {"intents": [{"intent": "happy"}, {"intent": "dance"}]})
        session.outbox.clear()  # the transport sent them, then the server died

        assert dict(vars(session.state)) == before
        assert session.handle({"v": 1, "type": "ctx", "mode": "companion", "activity": None, "attention": 0.3}) == []
        assert session.state.mode == "companion"


# ── the MCP surface ──────────────────────────────────────────────────────────


class TestMcpServer:
    def test_the_server_exposes_one_tool_per_safety_row(self):
        pytest.importorskip("httpx")
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
        from agentic.integrations.mcp.avatar_control.app import TOOLS as MCP_TOOLS

        names = {t.name for t in MCP_TOOLS}
        assert names == {f"hp.avatar.{tool}" for tool in safety.TOOL_SAFETY}

    def test_every_tool_declares_a_schema_and_a_description(self):
        pytest.importorskip("httpx")
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
        from agentic.integrations.mcp.avatar_control.app import TOOLS as MCP_TOOLS

        for tool in MCP_TOOLS:
            assert tool.description.strip(), tool.name
            assert tool.input_schema.get("type") == "object", tool.name

    def test_it_is_registered_in_the_forge_catalogue(self):
        from app.agentic.sync_service import _CORE_SERVERS

        entry = [s for s in _CORE_SERVERS if s[0] == "hp-avatar-control"]
        assert len(entry) == 1
        assert entry[0][1] == 9121

    def test_the_whitelist_hint_matches_the_real_whitelist(self):
        pytest.importorskip("httpx")
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
        from agentic.integrations.mcp.avatar_control.app import WHITELIST_HINT

        # A model reads this hint to choose an intent. If it drifts from §6.2 the model is
        # being told to ask for gestures the bridge will refuse.
        named = {w.strip(" .") for w in WHITELIST_HINT.split(":", 1)[1].split(",")}
        assert named == set(EMOTE_WHITELIST)
