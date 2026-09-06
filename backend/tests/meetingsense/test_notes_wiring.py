"""The notes engine, actually connected (batch MS12-a).

MS12 shipped a rolling-notes engine that was complete, tested, and **constructed by nothing**.
`start` echoed ``notes: true`` straight back to whatever asked for it, `MeetingSession`
accepted and drove a `notes=` engine correctly, and no route ever built one — so in the four
batches between MS12 and here, no meeting on any install had ever produced a `notes` frame,
and every client had been told notes were on.

Found while wiring MS9's vision bridge through the same constructor. This file is the test
that would have caught it, and the reason it did not exist is worth stating: MS12's suite
tested the engine, and MS3's tested the socket, and the gap was between them. So these tests
go through a **real WebSocket** and a **real avatar-session bridge** rather than through the
session core — the seam is the point.

The other half of the fix is smaller and matters as much: ``ready`` now reports whether notes
are running, not whether they were requested. A server that answers with the client's own
question can be wrong for four batches without anybody noticing.
"""

from __future__ import annotations

import base64
import io
import sqlite3
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

MS_ENV_VARS = ["MEETINGSENSE_ENABLED", "MEETINGSENSE_REMOTE",
               "MEETINGSENSE_NOTES_INTERVAL_S", "MEETINGSENSE_NOTES_MAX_WORDS"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in MS_ENV_VARS + ["MEETINGSENSE_NOTES_MODEL"]:
        monkeypatch.delenv(name, raising=False)


class Modules:
    def __init__(self):
        import app.meetingsense.avatar_bridge as avatar_bridge
        import app.meetingsense.config as config
        import app.meetingsense.notes_engine as notes_engine
        import app.meetingsense.routes as routes
        import app.meetingsense.session as session
        import app.meetingsense.store as store

        self.avatar_bridge = avatar_bridge
        self.config = config
        self.notes_engine = notes_engine
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


class StubSTT:
    name = "stub"
    available = True
    supports_segments = True

    async def transcribe_segments(self, data, *, fmt="wav", duration_s=None):
        return [{"t0": 0.0, "t1": duration_s, "text": "we should hold pricing at forty a seat",
                 "conf": 0.9}]


@pytest.fixture()
def stt(modules, monkeypatch):
    provider = StubSTT()
    import app.voice.providers as providers

    monkeypatch.setattr(providers, "get_meeting_stt_provider", lambda: provider)
    return provider


@pytest.fixture()
def model(modules, monkeypatch):
    """The compute router, watched. Answers a notes delta and then a recap."""
    calls = []

    async def call_model(messages, *, temperature=0.2, model=""):
        calls.append({"messages": messages, "model": model})
        joined = " ".join(m.get("content", "") for m in messages).lower()
        if "recap" in joined:
            return "They agreed to hold enterprise pricing at forty a seat."
        # `add_decisions`, not `decisions`: the model is asked for a *delta* against the notes
        # so far, and MS12 merges it. A stub answering with the merged shape would be testing
        # a protocol nothing speaks.
        return '{"add_decisions": [{"text": "Hold pricing at forty a seat", "t0": 0}]}'

    monkeypatch.setattr(modules.notes_engine, "call_model", call_model)
    return calls


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")
    # One utterance is a window here. The real thresholds are 60 s or 400 words, neither of
    # which a test can reach honestly — and driving them through the *config* rather than by
    # reaching into the engine is the point: it proves the factory carries them.
    monkeypatch.setenv("MEETINGSENSE_NOTES_MAX_WORDS", "1")


@pytest.fixture()
def client(modules):
    app = FastAPI()
    app.include_router(modules.routes.router)
    return TestClient(app)


def wav_b64(samples=None):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16_000)
        handle.writeframes(b"\x00\x01" * (samples or 16_000))
    return base64.b64encode(buf.getvalue()).decode()


def collect(ws):
    """Every frame queued, read by sending a ping and stopping at the pong.

    Not ``[receive_json() for _ in range(n)]``: when the server sends fewer frames than the
    test expects that reads a frame which never arrives and the test hangs, and a hang in CI
    is a timeout with no diagnosis. MS3 learned this the same way.
    """
    ws.send_json({"type": "ping"})
    frames = []
    while True:
        frame = ws.receive_json()
        if frame.get("type") == "pong":
            return frames
        frames.append(frame)


# ── the local socket ────────────────────────────────────────────────────────


class TestNotesOverTheSocket:
    def test_a_meeting_that_asks_for_notes_gets_them(self, client, enabled, stt, model, modules):
        # The end-to-end claim that was false for four batches: `notes: true` on the wire
        # produces a `notes` frame from a real socket.
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "start", "conversation_id": "c1", "notes": True})
            ready = ws.receive_json()
            ws.send_json({"type": "audio", "format": "wav", "data_b64": wav_b64(),
                          "t0": 0, "t1": 1_000})
            frames = collect(ws)

        assert ready["notes"] is True
        notes = [f for f in frames if f.get("type") == "notes"]
        assert notes, f"no notes frame among {[f.get('type') for f in frames]}"
        assert notes[0]["decisions"][0]["text"] == "Hold pricing at forty a seat"

    def test_ready_reports_what_the_server_will_do_not_what_was_asked(self, client, enabled, stt, modules):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "start", "conversation_id": "c1", "notes": False})
            assert ws.receive_json()["notes"] is False

    def test_ready_says_false_when_notes_were_asked_for_and_could_not_be_built(
        self, client, enabled, stt, modules, monkeypatch
    ):
        # The exact shape the bug wore, and the only case where echoing the request and
        # reporting the truth disagree: the client asks for notes, nothing can produce them,
        # and the old `ready` said yes. A server that answers with the client's own question
        # can be wrong for four batches without anybody noticing — as this one was.
        def broken(config):
            def build(meeting_id):
                raise RuntimeError("no compute backend is configured")

            return build

        monkeypatch.setattr(modules.notes_engine, "engine_factory", broken)
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "start", "conversation_id": "c1", "notes": True})
            ready = ws.receive_json()
            ws.send_json({"type": "audio", "format": "wav", "data_b64": wav_b64(),
                          "t0": 0, "t1": 1_000})
            frames = collect(ws)

        assert ready["notes"] is False
        # And the meeting records regardless: notes are never worth a transcript.
        assert [f for f in frames if f.get("type") == "segment"]

    def test_a_meeting_that_does_not_ask_takes_none(self, client, enabled, stt, model, modules):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "start", "conversation_id": "c1"})
            ws.receive_json()
            ws.send_json({"type": "audio", "format": "wav", "data_b64": wav_b64(),
                          "t0": 0, "t1": 1_000})
            frames = collect(ws)
        assert [f for f in frames if f.get("type") == "notes"] == []
        # And no model was spent on a meeting nobody asked to summarise.
        assert model == []

    def test_the_notes_land_in_the_store_for_the_summary_to_use(self, client, enabled, stt, model, modules):
        # MS14's summary message and MS13's recap tier both read the store, not the frame.
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "start", "conversation_id": "c1", "notes": True})
            meeting_id = ws.receive_json()["meeting_id"]
            ws.send_json({"type": "audio", "format": "wav", "data_b64": wav_b64(),
                          "t0": 0, "t1": 1_000})
            collect(ws)
        # `get_notes` wraps the body — the shape MS12 shipped and MS6's Markdown export was
        # silently missing until MS12 found it.
        body = modules.store.get_notes(meeting_id)["notes"]
        assert body["decisions"][0]["text"] == "Hold pricing at forty a seat"

    def test_stopping_forces_the_last_window(self, client, enabled, stt, model, modules, monkeypatch):
        # Without the forced final run the last minute of every meeting is missing from its
        # notes, and the summary is built from an incomplete picture.
        #
        # The thresholds go back to their real values here, which is the point: with a
        # one-word window the notes have already fired and there is nothing left to force, so
        # a test that shares the other fixtures' config would pass without the force at all.
        monkeypatch.delenv("MEETINGSENSE_NOTES_MAX_WORDS", raising=False)
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "start", "conversation_id": "c1", "notes": True})
            ws.receive_json()
            ws.send_json({"type": "audio", "format": "wav", "data_b64": wav_b64(),
                          "t0": 0, "t1": 1_000})
            # Nothing yet: one short utterance is neither 400 words nor 60 seconds.
            assert [f for f in collect(ws) if f.get("type") == "notes"] == []
            ws.send_json({"type": "stop"})
            # Read to `final` rather than pinging: the server closes the socket after it, so
            # a ping sent afterwards never gets its pong and the test would hang instead of
            # failing.
            frames = []
            while True:
                frame = ws.receive_json()
                frames.append(frame)
                if frame.get("type") == "final":
                    break
        assert [f.get("type") for f in frames].count("notes") >= 1

    def test_a_failing_model_never_takes_the_meeting_with_it(self, client, enabled, stt, modules, monkeypatch):
        async def angry(messages, **kwargs):
            raise RuntimeError("the model endpoint is down")

        monkeypatch.setattr(modules.notes_engine, "call_model", angry)
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "start", "conversation_id": "c1", "notes": True})
            ws.receive_json()
            ws.send_json({"type": "audio", "format": "wav", "data_b64": wav_b64(),
                          "t0": 0, "t1": 1_000})
            frames = collect(ws)
        # The transcript still arrives; only the notes are missing.
        assert [f for f in frames if f.get("type") == "segment"]
        assert [f for f in frames if f.get("type") == "notes"] == []


# ── the avatar session ──────────────────────────────────────────────────────


class TestNotesOverTheAvatarSession:
    def test_a_proxied_meeting_takes_notes_on_this_machine(self, modules, enabled, stt, model,
                                                           monkeypatch):
        # MS7's whole point is that the two transports are one core. A notes engine wired into
        # one and not the other would make that false in the way hardest to notice — a hosted
        # meeting that records perfectly and quietly summarises nothing.
        import asyncio

        monkeypatch.setenv("MEETINGSENSE_REMOTE", "true")

        async def scenario():
            outbox = []
            bridge = modules.avatar_bridge.MeetingBridge(outbox, config=modules.config.load_config())
            await bridge.handle({"type": "meeting_start", "conversation_id": "c1", "notes": True,
                                 "audio": {"channels": 1}})
            await bridge.handle({"type": "meeting_audio", "format": "wav",
                                 "data_b64": wav_b64(), "t0": 0, "t1": 1_000})
            return outbox

        outbox = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(scenario())
        frames = [m["meeting"] for m in outbox]
        assert frames[0].get("notes") is True, frames[0]
        assert "notes" in [f.get("type") for f in frames], [f.get("type") for f in frames]


# ── the factory ─────────────────────────────────────────────────────────────


class TestEngineFactory:
    def test_it_carries_the_configured_thresholds(self, modules, monkeypatch):
        monkeypatch.setenv("MEETINGSENSE_NOTES_INTERVAL_S", "17")
        monkeypatch.setenv("MEETINGSENSE_NOTES_MAX_WORDS", "42")
        engine = modules.notes_engine.engine_factory(modules.config.load_config())("m1")
        assert (engine.interval_s, engine.max_words) == (17, 42)

    def test_it_carries_the_configured_model(self, modules, monkeypatch):
        # The one thing a factory can silently drop, and the drop is invisible: notes still
        # appear, generated by whatever the router picks instead of what the operator set.
        seen = {}

        async def call_model(messages, *, temperature=0.2, model=""):
            seen["model"] = model
            return "{}"

        monkeypatch.setattr(modules.notes_engine, "call_model", call_model)
        monkeypatch.setenv("MEETINGSENSE_NOTES_MODEL", "qwen2.5:7b")
        import asyncio

        engine = modules.notes_engine.engine_factory(modules.config.load_config())("m1")
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            engine._call([{"role": "user", "content": "x"}])
        )
        assert seen["model"] == "qwen2.5:7b"

    def test_each_meeting_gets_its_own_engine(self, modules):
        # An engine holds one meeting's rolling state. One connection can record several
        # meetings in sequence, and a shared engine would carry the first one's recap into
        # the second one's notes.
        build = modules.notes_engine.engine_factory(modules.config.load_config())
        first, second = build("m1"), build("m2")
        assert first is not second
        assert (first.meeting_id, second.meeting_id) == ("m1", "m2")
