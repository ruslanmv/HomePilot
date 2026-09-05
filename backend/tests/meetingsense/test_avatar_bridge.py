"""MeetingSense over the avatar session (batch MS7, wave W2).

This is the batch MS2 was written for, and the test that matters is the one that proves it:
**the same script through both transports produces the same frames.** If that ever stops being
true, the hosted deployment has quietly acquired its own copy of the core, and the two will
drift in ways nobody notices until a meeting recorded from yourfriend.online is subtly
different from one recorded locally.

The second theme is that adding this must cost an existing client nothing. A client written
before MS7 sends no meeting frames and must behave exactly as it did; a client that sends one
to a server without MeetingSense must be ignored rather than errored at, because §6.9 makes an
unknown type a silent no-op and that is the only reason any of this needs no version bump.
"""

from __future__ import annotations

import array
import asyncio
import base64
import sqlite3

import pytest


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


MS_ENV_VARS = [
    "MEETINGSENSE_ENABLED",
    "MEETINGSENSE_REMOTE",
    "MEETINGSENSE_RESUME_GRACE_S",
    "STT_BASE_URL",
    "WHISPER_MODEL",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in MS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


class Modules:
    def __init__(self):
        import app.avatar_director.protocol as protocol
        import app.meetingsense.avatar_bridge as bridge
        import app.meetingsense.config as config
        import app.meetingsense.routes as routes
        import app.meetingsense.session as session
        import app.meetingsense.store as store

        self.protocol = protocol
        self.bridge = bridge
        self.config = config
        self.routes = routes
        self.session = session
        self.store = store


@pytest.fixture()
def modules(tmp_path, monkeypatch):
    mods = Modules()
    db = tmp_path / "meetings.sqlite3"

    def _connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(mods.store, "_connect", _connect)
    mods.store.migrate()
    mods.session._SESSIONS.clear()
    return mods


def stub_transcribe(script=None):
    """A speech provider as a plain callable, with a fixed script so two runs match."""
    lines = list(script or [])
    calls = []

    async def transcribe(data, *, fmt="wav", duration_s=None):
        calls.append({"fmt": fmt, "duration_s": duration_s, "bytes": len(data)})
        if lines:
            return lines.pop(0)
        return [{"t0": 0.0, "t1": duration_s, "text": f"line {len(calls)}", "conf": 0.9}]

    transcribe.calls = calls
    return transcribe


def pcm(samples=(1, 2, 3, 4)):
    return array.array("h", samples).tobytes()


def audio_frame(**extra):
    return {"format": "pcm16", "data_b64": base64.b64encode(pcm()).decode(), **extra}


def enabled_config(modules, *, remote=True, **kw):
    return modules.config.MeetingSenseConfig(
        enabled=True, flags=modules.config.SubFlags(remote=remote), **kw
    )


# ── the protocol additions ──────────────────────────────────────────────────


class TestProtocol:
    def test_the_version_does_not_move(self, modules):
        # The whole point of §6.9's silent-ignore rule: three new client types and one server
        # type, and every existing peer is still correct. A bump would make this a breaking
        # change for the avatar, the voice channel and the display panels as well.
        assert modules.protocol.PROTOCOL_VERSION == 1

    def test_the_new_types_are_declared(self, modules):
        assert modules.protocol.MEETING_CLIENT_TYPES <= modules.protocol.CLIENT_TYPES
        assert modules.protocol.MEETING_SERVER_TYPES <= modules.protocol.SERVER_TYPES

    def _handler(self, modules):
        handler = modules.protocol.ProtocolHandler(authenticate=lambda token: True)
        handler.handle({"v": 1, "type": "hello", "auth": "t", "client": "web"})
        return handler

    def test_a_meeting_frame_is_queued_and_answered_later(self, modules):
        # `handle()` is synchronous and a meeting transcribes audio. Queuing keeps the rule
        # the handler is built on — it decides what, never when.
        handler = self._handler(modules)
        assert handler.handle({"v": 1, "type": "meeting_start", "conversation_id": "c"}) == []
        assert len(handler.meeting_inbox) == 1

    def test_taking_the_frames_empties_the_inbox(self, modules):
        handler = self._handler(modules)
        for kind in ("meeting_start", "meeting_audio", "meeting_stop"):
            handler.handle({"v": 1, "type": kind})
        assert [m["type"] for m in handler.take_meeting_frames()] == [
            "meeting_start",
            "meeting_audio",
            "meeting_stop",
        ]
        assert handler.take_meeting_frames() == []

    def test_a_meeting_frame_still_needs_a_hello(self, modules):
        # Nothing about MeetingSense weakens the session's own auth.
        handler = modules.protocol.ProtocolHandler(authenticate=lambda token: True)
        replies = handler.handle({"v": 1, "type": "meeting_start", "conversation_id": "c"})
        assert replies[0]["type"] == "error"
        assert handler.meeting_inbox == []

    def test_an_old_client_is_untouched(self, modules):
        # The compatibility claim, asserted rather than assumed: a session that never mentions
        # a meeting behaves exactly as it did before this batch.
        handler = self._handler(modules)
        before = handler.handle({"v": 1, "type": "ctx", "mode": "focus", "attention": 0.5})
        assert before == []
        assert handler.meeting_inbox == []
        assert handler.outbox == []

    def test_an_unknown_meeting_subtype_is_still_ignored(self, modules):
        handler = self._handler(modules)
        assert handler.handle({"v": 1, "type": "meeting_marker", "t": 5}) == []
        assert "meeting_marker" in handler.ignored
        assert handler.meeting_inbox == []


class TestEnvelope:
    def test_it_carries_the_frame_untouched(self, modules):
        # One outbound type carrying an MS3 frame verbatim, rather than a flattened family of
        # meeting_segment / meeting_status / meeting_final. A new server frame then needs no
        # change here at all.
        frame = {"type": "segment", "id": "a", "seq": 1, "text": "hello"}
        wrapped = modules.bridge.envelope(frame)
        assert wrapped == {"v": 1, "type": "meeting", "meeting": frame}
        assert wrapped["meeting"] is frame


# ── the transport ───────────────────────────────────────────────────────────


class TestAvatarTransport:
    def test_it_is_the_protocol_and_nothing_more(self, modules):
        # MS2's contract: two methods. A convenience added here is a convenience the core
        # would learn to expect, and then there are two cores again.
        extra = {
            m
            for m in dir(modules.bridge.AvatarTransport)
            if not m.startswith("_") and m not in {"send", "close"}
        }
        assert extra == set()

    def test_it_writes_to_the_outbox_rather_than_the_socket(self, modules):
        # The avatar socket already has exactly one writer, the session loop. A second is how
        # interleaved frames and half-written JSON happen.
        outbox = []
        transport = modules.bridge.AvatarTransport(outbox)
        run(transport.send({"type": "segment", "text": "x"}))
        assert outbox == [{"v": 1, "type": "meeting", "meeting": {"type": "segment", "text": "x"}}]

    def test_closing_it_leaves_the_avatar_socket_alone(self, modules):
        # The socket outlives the meeting: it carries the persona, the gestures and the voice
        # channel. Closing it because a meeting ended would take the avatar down too.
        outbox = []
        run(modules.bridge.AvatarTransport(outbox).close())
        assert outbox == []


# ── the parity claim ────────────────────────────────────────────────────────


SCRIPT = [
    [{"t0": 0.0, "t1": 1.4, "text": "the launch moves to October", "conf": 0.9}],
    [{"t0": 0.0, "t1": 1.2, "text": "moves to October and legal", "conf": 0.8}],
]


#: A fixed clock for both runs. Without it the two `final` frames differ by a millisecond of
#: wall time, and a parity test that tolerates a difference is a parity test that would also
#: tolerate a real one.
FROZEN_CLOCK = 1_756_900_000.0


def drive_local(modules, config, transcribe):
    """The same meeting through MS3's local WebSocket path, minus the socket."""
    session = modules.session.MeetingSession(
        transport=modules.session.ListTransport(),
        config=config,
        transcribe=transcribe,
        now=lambda: FROZEN_CLOCK,
    )

    async def go():
        await session.start({"conversation_id": "conv-1", "title": "Q3", "audio": {"channels": 1}})
        for t0 in (0, 1_800):
            await modules.routes._handle_audio(session, audio_frame(t0=t0, t1=t0 + 1_400), 1)
        await session.stop()

    run(go())
    return session.transport.frames


def drive_avatar(modules, config, transcribe):
    """The same meeting through the avatar session's queue."""
    outbox = []
    bridge = modules.bridge.MeetingBridge(
        outbox, config=config, transcribe=transcribe, now=lambda: FROZEN_CLOCK
    )

    async def go():
        await bridge.handle(
            {"type": "meeting_start", "conversation_id": "conv-1", "title": "Q3", "audio": {"channels": 1}}
        )
        for t0 in (0, 1_800):
            await bridge.handle({"type": "meeting_audio", **audio_frame(t0=t0, t1=t0 + 1_400)})
        await bridge.handle({"type": "meeting_stop"})

    run(go())
    return [m["meeting"] for m in outbox]


def scrub(frames):
    """Drop the ids that differ between two runs of the same meeting, and only those.

    Not `elapsed`, and not the counts: those are behaviour, and a parity test that scrubbed
    them would pass for a bridge that reported the wrong duration. The clock is frozen instead.
    """
    out = []
    for frame in frames:
        copy = {k: v for k, v in frame.items() if k not in {"id", "meeting_id"}}
        out.append(copy)
    return out


class TestParity:
    def test_both_transports_produce_the_same_frames(self, modules):
        # The load-bearing test of MS7, and of MS2 before it. If this fails, the hosted
        # deployment has its own copy of the core and the two will drift silently.
        config = enabled_config(modules)
        local = drive_local(modules, config, stub_transcribe(list(SCRIPT)))
        avatar = drive_avatar(modules, config, stub_transcribe(list(SCRIPT)))
        assert scrub(avatar) == scrub(local)

    def test_the_frame_types_are_in_the_same_order(self, modules):
        config = enabled_config(modules)
        local = drive_local(modules, config, stub_transcribe(list(SCRIPT)))
        avatar = drive_avatar(modules, config, stub_transcribe(list(SCRIPT)))
        assert [f["type"] for f in avatar] == [f["type"] for f in local] == ["ready", "segment", "segment", "final"]

    def test_the_provider_is_called_identically(self, modules):
        # Same bytes, same format, same duration — the audio path is MS3's, not a second copy,
        # and this is what says so.
        config = enabled_config(modules)
        local_stt = stub_transcribe(list(SCRIPT))
        avatar_stt = stub_transcribe(list(SCRIPT))
        drive_local(modules, config, local_stt)
        drive_avatar(modules, config, avatar_stt)
        assert avatar_stt.calls == local_stt.calls

    def test_the_overlap_is_removed_the_same_way(self, modules):
        # The assembler is the same object type on both sides; a second implementation would
        # show up here as a duplicated phrase.
        config = enabled_config(modules)
        avatar = drive_avatar(modules, config, stub_transcribe(list(SCRIPT)))
        texts = [f["text"] for f in avatar if f["type"] == "segment"]
        assert texts == ["the launch moves to October", "and legal"]


# ── the bridge on its own ───────────────────────────────────────────────────


class TestBridge:
    def _bridge(self, modules, **kw):
        outbox = []
        config = kw.pop("config", enabled_config(modules))
        return outbox, modules.bridge.MeetingBridge(
            outbox, config=config, transcribe=kw.pop("transcribe", stub_transcribe())
        )

    def test_a_meeting_reaches_the_store(self, modules):
        outbox, bridge = self._bridge(modules)
        run(bridge.handle({"type": "meeting_start", "conversation_id": "conv-1", "title": "Q3"}))
        assert modules.store.get_meeting(bridge.session.meeting_id)["title"] == "Q3"

    def test_a_stereo_frame_is_split_the_same_way(self, modules):
        # ch0 → them, ch1 → me. Two implementations of this would drift into swapping them,
        # and nothing in the stack would notice.
        outbox, bridge = self._bridge(
            modules,
            transcribe=stub_transcribe(
                [
                    [{"t0": 0.0, "t1": 1.0, "text": "from the call", "conf": 0.9}],
                    [{"t0": 0.0, "t1": 1.0, "text": "from my mic", "conf": 0.9}],
                ]
            ),
        )
        run(bridge.handle({"type": "meeting_start", "conversation_id": "c", "audio": {"channels": 2}}))
        run(bridge.handle({"type": "meeting_audio", **audio_frame(t0=0, t1=1_000)}))
        segments = [m["meeting"] for m in outbox if m["meeting"]["type"] == "segment"]
        assert [(s["speaker"], s["text"]) for s in segments] == [
            ("them", "from the call"),
            ("me", "from my mic"),
        ]

    def test_audio_before_a_start_is_refused_not_fatal(self, modules):
        outbox, bridge = self._bridge(modules)
        run(bridge.handle({"type": "meeting_audio", **audio_frame()}))
        assert outbox[-1]["meeting"] == {
            "type": "error",
            "code": "not_live",
            "msg": "no meeting has been started",
        }

    def test_a_bad_audio_frame_does_not_end_the_avatar_session(self, modules):
        # The socket is carrying the persona, the gestures and possibly a spoken
        # conversation. Dropping all of that because a chunk of audio was malformed would be
        # a poor trade.
        outbox, bridge = self._bridge(modules)
        run(bridge.handle({"type": "meeting_start", "conversation_id": "c"}))
        run(bridge.handle({"type": "meeting_audio", "format": "pcm16", "data_b64": "not base64!"}))
        assert outbox[-1]["meeting"]["code"] == "audio_undecodable"
        # And the meeting is still going.
        run(bridge.handle({"type": "meeting_audio", **audio_frame(t0=0, t1=1_000)}))
        assert outbox[-1]["meeting"]["type"] == "segment"

    def test_a_provider_that_raises_is_reported_not_propagated(self, modules):
        async def boom(data, *, fmt="wav", duration_s=None):
            raise RuntimeError("model gone")

        outbox, bridge = self._bridge(modules, transcribe=boom)
        run(bridge.handle({"type": "meeting_start", "conversation_id": "c"}))
        run(bridge.handle({"type": "meeting_audio", **audio_frame()}))
        assert outbox[-1]["meeting"]["code"] == "frame_failed"

    def test_starting_twice_is_refused(self, modules):
        outbox, bridge = self._bridge(modules)
        run(bridge.handle({"type": "meeting_start", "conversation_id": "c"}))
        run(bridge.handle({"type": "meeting_start", "conversation_id": "c"}))
        assert outbox[-1]["meeting"]["code"] == "already_started"

    def test_a_second_meeting_may_follow_the_first(self, modules):
        # An avatar socket is long-lived and may run several meetings in a row.
        outbox, bridge = self._bridge(modules)
        run(bridge.handle({"type": "meeting_start", "conversation_id": "c"}))
        first = bridge.session.meeting_id
        run(bridge.handle({"type": "meeting_stop"}))
        run(bridge.handle({"type": "meeting_start", "conversation_id": "c"}))
        assert bridge.session.meeting_id != first

    def test_a_start_with_no_conversation_is_named(self, modules):
        outbox, bridge = self._bridge(modules)
        run(bridge.handle({"type": "meeting_start"}))
        assert outbox[-1]["meeting"]["code"] == "conversation_required"

    def test_an_unknown_queued_type_is_ignored(self, modules):
        outbox, bridge = self._bridge(modules)
        run(bridge.handle({"type": "meeting_marker", "t": 1}))
        assert outbox == []


class TestFlags:
    def test_the_master_flag_refuses(self, modules):
        outbox = []
        bridge = modules.bridge.MeetingBridge(
            outbox, config=modules.config.MeetingSenseConfig(enabled=False), transcribe=stub_transcribe()
        )
        run(bridge.handle({"type": "meeting_start", "conversation_id": "c"}))
        assert outbox[-1]["meeting"]["code"] == "disabled"
        assert bridge.session is None

    def test_the_remote_flag_is_separate_from_the_master(self, modules):
        # An operator who wants meetings on their own machine has not thereby agreed to
        # accept them from a hosted page.
        outbox = []
        bridge = modules.bridge.MeetingBridge(
            outbox, config=enabled_config(modules, remote=False), transcribe=stub_transcribe()
        )
        run(bridge.handle({"type": "meeting_start", "conversation_id": "c"}))
        assert outbox[-1]["meeting"]["code"] == "remote_disabled"
        assert bridge.session is None

    def test_a_refusal_never_touches_the_store(self, modules, monkeypatch):
        called = []
        monkeypatch.setattr(modules.store, "migrate_if_enabled", lambda cfg: called.append(cfg))
        outbox = []
        bridge = modules.bridge.MeetingBridge(
            outbox, config=enabled_config(modules, remote=False), transcribe=stub_transcribe()
        )
        run(bridge.handle({"type": "meeting_start", "conversation_id": "c"}))
        assert called == []


class TestDisconnect:
    def test_a_dropped_avatar_socket_suspends_the_meeting(self, modules):
        # MS3-a's grace window, reused: somebody on a hosted page loses their connection for
        # the same reasons a local one does and deserves the same answer.
        outbox = []
        bridge = modules.bridge.MeetingBridge(
            outbox, config=enabled_config(modules), transcribe=stub_transcribe()
        )
        run(bridge.handle({"type": "meeting_start", "conversation_id": "c"}))
        meeting_id = bridge.session.meeting_id
        run(bridge.close())
        assert modules.store.get_meeting(meeting_id)["status"] == "suspended"

    def test_zero_grace_ends_it_instead(self, modules):
        outbox = []
        config = enabled_config(modules, resume=modules.config.ResumeConfig(grace_s=0))
        bridge = modules.bridge.MeetingBridge(outbox, config=config, transcribe=stub_transcribe())
        run(bridge.handle({"type": "meeting_start", "conversation_id": "c"}))
        meeting_id = bridge.session.meeting_id
        run(bridge.close())
        assert modules.store.get_meeting(meeting_id)["status"] == "ended"

    def test_closing_without_a_meeting_is_a_no_op(self, modules):
        outbox = []
        bridge = modules.bridge.MeetingBridge(
            outbox, config=enabled_config(modules), transcribe=stub_transcribe()
        )
        run(bridge.close())
        assert outbox == []


class TestWiring:
    def test_the_avatar_session_builds_a_bridge(self, modules):
        # The ignition, not the engine: everything above can be perfect and never called.
        import app.avatar_director.session as avatar_session

        handler = modules.protocol.ProtocolHandler(authenticate=lambda t: True)
        bridge = avatar_session._meeting_bridge(handler)
        assert bridge is not None
        # And it writes into the handler's outbox, which is the socket's single writer.
        assert bridge.outbox is handler.outbox

    def test_a_build_without_meetingsense_still_serves_avatars(self, modules, monkeypatch):
        # An ImportError here would take the whole avatar socket down to report that an
        # optional feature is missing.
        import builtins

        import app.avatar_director.session as avatar_session

        real_import = builtins.__import__

        def fail(name, *args, **kwargs):
            if "avatar_bridge" in name:
                raise ImportError("no meetingsense in this build")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fail)
        handler = modules.protocol.ProtocolHandler(authenticate=lambda t: True)
        assert avatar_session._meeting_bridge(handler) is None


# ── MS8: what a hosted client is told, and what it is refused ───────────────


class TestRemoteOk:
    """`/v1/meetingsense/status` answers "may a meeting arrive over the avatar session?".

    One boolean rather than two flags for a client to combine, because the two deliberately do
    not imply each other and a client that guessed the relationship would guess wrong in the
    direction that matters: offering a control the server will refuse.
    """

    def _client(self, modules):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(modules.routes.router)
        return TestClient(app)

    def _status(self, modules, monkeypatch, **env):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        import app.voice.providers as providers

        class Ready:
            name = "whisper-local"
            available = True
            supports_segments = True
            device = "cuda"

        monkeypatch.setattr(providers, "get_stt_provider", lambda: Ready())
        return self._client(modules).get("/v1/meetingsense/status").json()

    def test_it_is_false_while_meetingsense_is_off(self, modules, monkeypatch):
        assert self._status(modules, monkeypatch)["remote_ok"] is False

    def test_it_is_false_with_the_master_flag_on_but_remote_off(self, modules, monkeypatch):
        # The shipped default. Somebody who turned MeetingSense on for their own recorder has
        # not thereby opened it to a hosted page.
        body = self._status(modules, monkeypatch, MEETINGSENSE_ENABLED="true")
        assert body["enabled"] is True
        assert body["ready"] is True
        assert body["remote_ok"] is False

    def test_it_is_true_only_when_both_are_on(self, modules, monkeypatch):
        body = self._status(
            modules, monkeypatch, MEETINGSENSE_ENABLED="true", MEETINGSENSE_REMOTE="true"
        )
        assert body["remote_ok"] is True

    def test_it_is_false_when_nothing_can_transcribe(self, modules, monkeypatch):
        # Honest rather than optimistic: a client told `remote_ok` would start a meeting, and a
        # server with no speech provider would refuse every audio frame it then sent.
        monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")
        monkeypatch.setenv("MEETINGSENSE_REMOTE", "true")
        import app.voice.providers as providers

        monkeypatch.setattr(providers, "get_stt_provider", lambda: None)
        assert self._client(modules).get("/v1/meetingsense/status").json()["remote_ok"] is False


class TestRemoteRefusal:
    """MS8's other half: with `_REMOTE` off, avatar-session meeting frames are refused."""

    def _bridge(self, modules, *, remote):
        outbox = []
        return outbox, modules.bridge.MeetingBridge(
            outbox, config=enabled_config(modules, remote=remote), transcribe=stub_transcribe()
        )

    def test_every_meeting_frame_is_refused_not_just_the_start(self, modules):
        # A client that ignored the refusal and carried on must not find a later frame
        # accepted: the gate is checked per frame, not once at start.
        outbox, bridge = self._bridge(modules, remote=False)
        for frame in (
            {"type": "meeting_start", "conversation_id": "c"},
            {"type": "meeting_audio", **audio_frame()},
            {"type": "meeting_stop"},
        ):
            run(bridge.handle(frame))
        assert [m["meeting"]["code"] for m in outbox] == ["remote_disabled"] * 3

    def test_the_refusal_names_the_reason_rather_than_the_flag(self, modules):
        # A hosted client cannot set an environment variable on somebody else's machine, so
        # naming the variable would be advice it cannot act on. It is told what is true.
        outbox, bridge = self._bridge(modules, remote=False)
        run(bridge.handle({"type": "meeting_start", "conversation_id": "c"}))
        assert "avatar session" in outbox[-1]["meeting"]["msg"]

    def test_no_meeting_is_created(self, modules):
        outbox, bridge = self._bridge(modules, remote=False)
        run(bridge.handle({"type": "meeting_start", "conversation_id": "c"}))
        assert bridge.session is None
        assert modules.store.list_meetings() == []

    def test_the_local_socket_is_unaffected_by_the_remote_flag(self, modules):
        # `_REMOTE` gates the avatar path only. Somebody recording on their own machine keeps
        # working exactly as they did in W1.
        outbox, bridge = self._bridge(modules, remote=False)
        session = modules.session.MeetingSession(
            transport=modules.session.ListTransport(),
            config=enabled_config(modules, remote=False),
            transcribe=stub_transcribe(),
        )
        run(session.start({"conversation_id": "conv-1"}))
        assert session.transport.frames[0]["type"] == "ready"
