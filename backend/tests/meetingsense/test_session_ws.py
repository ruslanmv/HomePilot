"""``WS /v1/meetingsense/session`` — the local transport (batch MS3).

MS2 built a core that has never met a socket. This is the first thing that connects the two,
so the tests are about the seam rather than about transcription: does a wire frame become the
call the core expects, does the core's answer become a frame, and does a client that
misbehaves get told rather than disconnected.

Two things here are load-bearing beyond MS3.

**Refusing when the flag is off must look like the voice route's refusal** — accept, say why,
close 1008 — because a client that gets a bare connection failure cannot tell "disabled" from
"wrong URL" from "server down", and the entry point in MS5 has to explain which it is.

**A stereo frame is two speakers.** MS4's mixer keeps system audio and microphone on separate
gain nodes, and channel 0 is the system. If that convention is wrong, every transcript comes
out with the speakers swapped, and nothing else in the stack would notice.
"""

from __future__ import annotations

import array
import base64
import io
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Imported inside fixtures, never at module scope: `tests/conftest.py` purges `app.*` from
# `sys.modules`, so a module captured at collection time is a different object from the one
# the route runs in, and a patch would land on the wrong one.

MS_ENV_VARS = ["MEETINGSENSE_ENABLED", "MEETINGSENSE_RETENTION", "STT_BASE_URL", "WHISPER_MODEL"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in MS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


class Modules:
    def __init__(self):
        import app.meetingsense.audio as audio
        import app.meetingsense.routes as routes
        import app.meetingsense.session as session
        import app.meetingsense.store as store

        self.audio = audio
        self.routes = routes
        self.session = session
        self.store = store


@pytest.fixture()
def modules(tmp_path, monkeypatch):
    """The live modules, with the store pointed at a throwaway database."""
    import sqlite3

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
    """A speech provider that returns whatever it was told to, and records what it was given.

    Deliberately not a mock of ``transcribe``: the route must call ``transcribe_segments``,
    because that is the method that carries timings. A stub with only ``transcribe`` would
    make a route that silently lost them look fine.
    """

    name = "stub"
    available = True
    supports_segments = True

    def __init__(self, script=None):
        self.script = list(script or [])
        self.calls = []

    async def transcribe_segments(self, data, *, fmt="wav", duration_s=None):
        self.calls.append({"data": data, "fmt": fmt, "duration_s": duration_s})
        if self.script:
            return self.script.pop(0)
        return [{"t0": 0.0, "t1": duration_s, "text": "hello", "conf": 0.9}]


@pytest.fixture()
def stt(modules, monkeypatch):
    provider = StubSTT()
    import app.voice.providers as providers

    monkeypatch.setattr(providers, "get_stt_provider", lambda: provider)
    return provider


@pytest.fixture()
def client(modules):
    app = FastAPI()
    app.include_router(modules.routes.router)
    return TestClient(app)


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")


# ── helpers ─────────────────────────────────────────────────────────────────


def pcm(samples):
    return array.array("h", samples).tobytes()


def b64(data):
    return base64.b64encode(data).decode()


def wav(samples, *, rate=16_000, channels=1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm(samples))
    return buf.getvalue()


def start(ws, **extra):
    ws.send_json({"type": "start", "conversation_id": "conv-1", **extra})
    return ws.receive_json()


def collect(ws):
    """Every frame the server has queued, read by sending a ping and stopping at the pong.

    Not ``[receive_json() for _ in range(n)]``: when the server sends *fewer* frames than the
    test expects, that reads a frame that never arrives and the test hangs. A hang in CI is a
    timeout with no diagnosis, which is a worse way to learn about a regression than a failed
    assertion. The ping is answered after whatever the previous frame produced, so the pong is
    a reliable end marker.
    """
    ws.send_json({"type": "ping"})
    frames = []
    while True:
        frame = ws.receive_json()
        if frame.get("type") == "pong":
            return frames
        frames.append(frame)


# ── the flag ────────────────────────────────────────────────────────────────


class TestFlag:
    def test_disabled_says_so_and_closes_rather_than_refusing_the_handshake(self, client):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            # The ping is here so that a server which *stopped* refusing fails this test
            # rather than hanging it: the refusal is queued before any frame is read, so a
            # working gate still answers `error` first, and a missing gate answers `pong`.
            ws.send_json({"type": "ping"})
            frame = ws.receive_json()
        assert frame["type"] == "error"
        assert frame["code"] == "disabled"

    def test_disabled_never_touches_the_store(self, client, modules, monkeypatch):
        # The refusal has to come before any table is created: an install that never enables
        # MeetingSense must not grow its schema because somebody's browser reconnected.
        called = []
        monkeypatch.setattr(modules.store, "migrate_if_enabled", lambda cfg: called.append(cfg))
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["code"] == "disabled"
        assert called == []

    def test_enabled_accepts_a_start(self, client, enabled, stt):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ready = start(ws)
        assert ready["type"] == "ready"
        assert ready["stt"] is True
        assert ready["meeting_id"]


# ── start ───────────────────────────────────────────────────────────────────


class TestStart:
    def test_a_start_without_a_conversation_is_an_error_not_a_disconnect(self, client, enabled, stt):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "start"})
            frame = ws.receive_json()
            assert frame["type"] == "error"
            assert frame["code"] == "conversation_required"
            # Still usable: the client can correct itself without reconnecting.
            assert start(ws)["type"] == "ready"

    def test_the_meeting_reaches_the_store(self, client, enabled, stt, modules):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ready = start(ws, title="Q3 planning", source="teams")
        row = modules.store.get_meeting(ready["meeting_id"])
        assert row["title"] == "Q3 planning"
        assert row["conversation_id"] == "conv-1"

    def test_a_live_session_is_findable_by_conversation(self, client, enabled, stt, modules):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            # MS18's context provider looks a meeting up this way; the registration has to
            # happen while the socket is open, not at stop.
            assert modules.session.for_conversation("conv-1") is not None

    def test_without_speech_it_still_starts_and_says_stt_false(self, client, enabled, monkeypatch):
        import app.voice.providers as providers

        monkeypatch.setattr(providers, "get_stt_provider", lambda: None)
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ready = start(ws)
        # A meeting that records slides and markers without a transcript is still a meeting.
        assert ready["type"] == "ready"
        assert ready["stt"] is False

    def test_a_provider_that_raises_on_import_is_not_fatal(self, client, enabled, monkeypatch):
        import app.voice.providers as providers

        def boom():
            raise RuntimeError("no ctranslate2")

        monkeypatch.setattr(providers, "get_stt_provider", boom)
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            assert start(ws)["stt"] is False


# ── audio ───────────────────────────────────────────────────────────────────


class TestAudio:
    def test_a_wav_frame_becomes_a_segment(self, client, enabled, stt):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json(
                {"type": "audio", "format": "wav", "data_b64": b64(wav([1, 2, 3])), "t0": 0, "t1": 1_400}
            )
            frame = ws.receive_json()
        assert frame["type"] == "segment"
        assert frame["text"] == "hello"
        assert frame["id"]

    def test_the_timings_come_from_transcribe_segments_not_from_the_frame(self, client, enabled, stt):
        stt.script = [[{"t0": 0.25, "t1": 0.75, "text": "measured", "conf": 0.8}]]
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json(
                {"type": "audio", "format": "wav", "data_b64": b64(wav([1])), "t0": 10_000, "t1": 12_000}
            )
            frame = ws.receive_json()
        # Chunk-relative 250–750 ms, offset by where the chunk sat.
        assert frame["t0"] == 10_250
        assert frame["t1"] == 10_750

    def test_the_frame_length_is_passed_as_duration(self, client, enabled, stt):
        # The client framed this audio and knows how long it is; a provider that only returns
        # text does not, and would report an unmeasured end for a span whose length was never
        # in doubt.
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json(
                {"type": "audio", "format": "wav", "data_b64": b64(wav([1])), "t0": 1_000, "t1": 3_400}
            )
            ws.receive_json()
        assert stt.calls[0]["duration_s"] == pytest.approx(2.4)

    def test_raw_pcm16_reaches_the_provider_as_a_wav(self, client, enabled, stt):
        # `transcribe` writes the bytes to a `.wav` temp file. Headerless PCM named `.wav`
        # is read as if its first 44 bytes were a header — a garbled transcript, not an
        # exception, which is the worst way for this to fail.
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json({"type": "audio", "format": "pcm16", "data_b64": b64(pcm([1, 2, 3, 4]))})
            ws.receive_json()
        assert stt.calls[0]["data"][:4] == b"RIFF"
        assert stt.calls[0]["fmt"] == "wav"

    def test_the_design_documents_field_name_also_works(self, client, enabled, stt):
        # D6 fixed `data_b64`; the design document spells it `pcm16_b64`. A client written
        # from the document should work rather than fail with "audio missing".
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json({"type": "audio", "pcm16_b64": b64(pcm([1, 2]))})
            assert ws.receive_json()["type"] == "segment"

    def test_a_stereo_frame_is_two_speakers(self, client, enabled, stt):
        stt.script = [
            [{"t0": 0.0, "t1": 1.0, "text": "from the call", "conf": 0.9}],
            [{"t0": 0.0, "t1": 1.0, "text": "from my mic", "conf": 0.9}],
        ]
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws, audio={"rate": 16_000, "channels": 2, "mode": "system+mic"})
            ws.send_json({"type": "audio", "format": "pcm16", "data_b64": b64(pcm([5, -5, 6, -6]))})
            frames = collect(ws)
        # Channel 0 is the system audio — the other people — and channel 1 is this machine's
        # microphone. Swap those and every transcript comes out attributed backwards.
        assert [(f["speaker"], f["text"]) for f in frames] == [
            ("them", "from the call"),
            ("me", "from my mic"),
        ]

    def test_each_channel_carries_only_its_own_samples(self, client, enabled, stt):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws, audio={"channels": 2})
            ws.send_json({"type": "audio", "format": "pcm16", "data_b64": b64(pcm([1, -1, 2, -2, 3, -3]))})
            collect(ws)
        left, right = (array.array("h", c["data"][44:]).tolist() for c in stt.calls)
        assert left == [1, 2, 3]
        assert right == [-1, -2, -3]

    def test_the_two_channels_do_not_dedupe_against_each_other(self, client, enabled, stt):
        # Both people say the same words — bleed, or simply agreement. One shared assembler
        # would drop the second and attribute the line to whichever channel was transcribed
        # first, which is arbitrary.
        stt.script = [
            [{"t0": 0.0, "t1": 1.0, "text": "yes exactly that", "conf": 0.9}],
            [{"t0": 0.0, "t1": 1.0, "text": "yes exactly that", "conf": 0.9}],
        ]
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws, audio={"channels": 2})
            ws.send_json({"type": "audio", "format": "pcm16", "data_b64": b64(pcm([1, -1]))})
            frames = collect(ws)
        assert [f["speaker"] for f in frames] == ["them", "me"]
        assert all(f["text"] == "yes exactly that" for f in frames)

    def test_a_chunk_that_is_all_overlap_sends_nothing(self, client, enabled, stt):
        stt.script = [
            [{"t0": 0.0, "t1": 2.0, "text": "we still need legal sign-off", "conf": 0.9}],
            [{"t0": 0.0, "t1": 1.0, "text": "need legal sign-off", "conf": 0.9}],
        ]
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json({"type": "audio", "format": "pcm16", "data_b64": b64(pcm([1])), "t0": 0})
            assert ws.receive_json()["type"] == "segment"
            ws.send_json({"type": "audio", "format": "pcm16", "data_b64": b64(pcm([1])), "t0": 1_800})
            # Nothing new was said, so nothing is sent. Proven by the next frame arriving.
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"

    def test_audio_before_start_is_an_error_not_a_crash(self, client, enabled, stt):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "audio", "format": "pcm16", "data_b64": b64(pcm([1]))})
            frame = ws.receive_json()
        assert frame["type"] == "error"
        assert frame["code"] == "not_live"

    def test_audio_without_a_provider_is_a_named_refusal(self, client, enabled, monkeypatch):
        import app.voice.providers as providers

        monkeypatch.setattr(providers, "get_stt_provider", lambda: None)
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json({"type": "audio", "format": "pcm16", "data_b64": b64(pcm([1]))})
            frame = ws.receive_json()
        assert frame["code"] == "stt_unavailable"

    def test_a_provider_that_raises_does_not_end_the_meeting(self, client, enabled, stt):
        async def boom(data, *, fmt="wav", duration_s=None):
            raise RuntimeError("model gone")

        stt.transcribe_segments = boom
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json({"type": "audio", "format": "pcm16", "data_b64": b64(pcm([1]))})
            assert ws.receive_json()["code"] == "frame_failed"
            # The recording survives one failed chunk.
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"


class TestBadAudioFrames:
    def test_no_audio_at_all(self, client, enabled, stt):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json({"type": "audio", "format": "pcm16"})
            assert ws.receive_json()["code"] == "audio_missing"

    def test_not_base64(self, client, enabled, stt):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json({"type": "audio", "format": "pcm16", "data_b64": "not base64!!"})
            assert ws.receive_json()["code"] == "audio_undecodable"

    def test_an_unknown_format(self, client, enabled, stt):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json({"type": "audio", "format": "flac", "data_b64": b64(b"\x00\x00")})
            assert ws.receive_json()["code"] == "audio_format"

    def test_pcm_that_is_not_a_whole_number_of_samples(self, client, enabled, stt):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json({"type": "audio", "format": "pcm16", "data_b64": b64(b"\x01\x02\x03")})
            assert ws.receive_json()["code"] == "audio_misaligned"

    def test_a_frame_larger_than_the_cap(self, client, enabled, stt, modules):
        oversized = b"\x00" * (modules.audio.MAX_FRAME_BYTES + 2)
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json({"type": "audio", "format": "pcm16", "data_b64": b64(oversized)})
            assert ws.receive_json()["code"] == "audio_too_large"

    def test_a_wav_that_is_not_a_wav(self, client, enabled, stt):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws, audio={"channels": 2})
            ws.send_json({"type": "audio", "format": "wav", "data_b64": b64(b"nonsense here")})
            assert ws.receive_json()["code"] == "audio_format"


# ── partials ────────────────────────────────────────────────────────────────


class TestPartials:
    def test_a_partial_frame_is_provisional_text(self, client, enabled, stt):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json(
                {"type": "audio", "partial": True, "format": "pcm16", "data_b64": b64(pcm([1])), "t0": 500}
            )
            frame = ws.receive_json()
        assert frame["type"] == "partial"
        assert frame["text"] == "hello"

    def test_a_partial_is_not_stored(self, client, enabled, stt, modules):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ready = start(ws)
            ws.send_json({"type": "audio", "partial": True, "format": "pcm16", "data_b64": b64(pcm([1]))})
            ws.receive_json()
        assert modules.store.get_segments(ready["meeting_id"]) == []

    def test_a_partial_does_not_make_the_real_segment_look_like_a_repeat(self, client, enabled, stt):
        # The same audio arrives again when the utterance closes. If the partial had fed the
        # assembler, the closing chunk would be trimmed away as a duplicate of itself and the
        # meeting would lose the line entirely.
        stt.script = [
            [{"t0": 0.0, "t1": 1.0, "text": "the launch moves to October", "conf": 0.9}],
            [{"t0": 0.0, "t1": 1.0, "text": "the launch moves to October", "conf": 0.9}],
        ]
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json({"type": "audio", "partial": True, "format": "pcm16", "data_b64": b64(pcm([1]))})
            assert ws.receive_json()["type"] == "partial"
            ws.send_json({"type": "audio", "format": "pcm16", "data_b64": b64(pcm([1]))})
            frame = ws.receive_json()
        assert frame["type"] == "segment"
        assert frame["text"] == "the launch moves to October"


# ── the rest of the vocabulary ──────────────────────────────────────────────


class TestOtherFrames:
    def test_mute_echoes_status(self, client, enabled, stt):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json({"type": "mute", "mic": True})
            frame = ws.receive_json()
        assert frame["type"] == "status"
        assert frame["mic_muted"] is True

    def test_a_keyframe_is_recorded_and_counted(self, client, enabled, stt, modules):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ready = start(ws)
            ws.send_json({"type": "keyframe", "t": 4_000, "url": "/files/slide-1.png"})
            # MS10: the slide is announced the moment it is taken, before any caption. The
            # strip has to show it now — a slide that appeared only once a vision model
            # answered would look like a slide that was missed.
            slide = ws.receive_json()
            ws.send_json({"type": "status"})
            status = ws.receive_json()
        assert slide["type"] == "slide"
        assert (slide["t"], slide["url"], slide["caption"]) == (4_000, "/files/slide-1.png", None)
        assert status["slides"] == 1
        assert modules.store.get_keyframes(ready["meeting_id"])[0]["url"] == "/files/slide-1.png"

    def test_a_keyframe_without_a_url_is_named(self, client, enabled, stt):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json({"type": "keyframe", "t": 1})
            assert ws.receive_json()["code"] == "url_required"

    def test_ping_answers_pong(self, client, enabled, stt):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

    def test_an_unknown_type_is_ignored_rather_than_fatal(self, client, enabled, stt):
        # `marker` and `ask` belong to waves that are not built. A client sending them early
        # should lose the feature it asked for, not the meeting it is recording.
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json({"type": "marker", "t": 900, "label": "important"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"


# ── stop ────────────────────────────────────────────────────────────────────


class TestStop:
    def test_stop_answers_final_with_the_counts(self, client, enabled, stt):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json({"type": "audio", "format": "pcm16", "data_b64": b64(pcm([1]))})
            ws.receive_json()
            ws.send_json({"type": "stop"})
            final = ws.receive_json()
        assert final["type"] == "final"
        assert final["segments"] == 1

    def test_stop_closes_the_meeting_in_the_store(self, client, enabled, stt, modules):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ready = start(ws)
            ws.send_json({"type": "stop"})
            ws.receive_json()
        assert modules.store.get_meeting(ready["meeting_id"])["ended_at"] is not None

    def test_stop_deregisters_the_session(self, client, enabled, stt, modules):
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            start(ws)
            ws.send_json({"type": "stop"})
            ws.receive_json()
        assert modules.session.live_sessions() == {}

    def test_a_dropped_socket_ends_the_meeting_when_there_is_no_grace(self, client, enabled, stt, modules, monkeypatch):
        # MS3's behaviour, and still reachable: `MEETINGSENSE_RESUME_GRACE_S=0` says a drop is
        # final. D10 changed the default, not the option — somebody who would rather lose a
        # recording than have a half-open one can still have that.
        monkeypatch.setenv("MEETINGSENSE_RESUME_GRACE_S", "0")
        with client.websocket_connect("/v1/meetingsense/session") as ws:
            ready = start(ws)
        assert modules.store.get_meeting(ready["meeting_id"])["ended_at"] is not None
        assert modules.session.live_sessions() == {}


# ── the transport is only two methods ───────────────────────────────────────


class TestTransport:
    def test_the_websocket_transport_is_the_protocol_and_nothing_more(self, modules):
        # MS7's second transport is free only for as long as this stays a pair of forwarding
        # methods. A convenience added here is a convenience the core learns to expect.
        extra = {
            m
            for m in dir(modules.routes.WebSocketTransport)
            if not m.startswith("_") and m not in {"send", "close"}
        }
        assert extra == set()

    def test_it_forwards_to_the_socket(self, modules):
        import asyncio

        sent = []

        class FakeWS:
            async def send_json(self, frame):
                sent.append(frame)

            async def close(self):
                sent.append("closed")

        transport = modules.routes.WebSocketTransport(FakeWS())
        loop = asyncio.new_event_loop()
        loop.run_until_complete(transport.send({"type": "x"}))
        loop.run_until_complete(transport.close())
        loop.close()
        assert sent == [{"type": "x"}, "closed"]
