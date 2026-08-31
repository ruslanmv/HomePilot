"""Vision (B15) — the size cap, the whitelist, and what the endpoint refuses.

``test_vision_retention.py`` holds the other half: that nothing reaches disk or logs. This
file is about the checks either side of the model call, all of which run with an injected
analyser so the tests need neither a VLM nor ``httpx``.
"""

from __future__ import annotations

import asyncio
import base64
import struct

import pytest

from app.avatar_director.config import AvatarDirectorConfig, VisionConfig
from app.avatar_director.protocol import EMOTE_WHITELIST, ProtocolHandler
from app.avatar_director.vision import (
    MAX_BODY_BYTES,
    VisionError,
    VisionService,
    decode_frame,
    image_dimensions,
    insight_message,
)


# ── fixtures made of bytes, not files ────────────────────────────────────────


def png(width: int, height: int) -> bytes:
    """A PNG header carrying the dimensions a test wants. Not a valid image beyond that,
    which is the point: the cap is read from the header and nothing decodes it."""
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height) + b"\x08\x02" * 4


def jpeg(width: int, height: int) -> bytes:
    """A JPEG with one APP0 segment and one SOF0 carrying the size — enough to walk."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof0 = b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", height, width) + b"\x03" + b"\x00" * 9
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def config(model: str = "moondream", max_px: int = 768) -> AvatarDirectorConfig:
    return AvatarDirectorConfig(enabled=True, vision=VisionConfig(model=model, max_image_px=max_px))


def service(answer="A bar chart with a broken y-axis.", *, fail=None, cfg=None) -> VisionService:
    seen = []

    async def analyze(**kwargs):
        seen.append(kwargs)
        if fail is not None:
            raise fail
        if answer is None:
            return {"ok": False, "error": "no model installed"}
        return {"ok": True, "analysis_text": answer}

    svc = VisionService(cfg or config(), analyze=analyze)
    svc.calls = seen
    return svc


def insight(svc, raw=None, prompt="", ctx=None):
    return asyncio.run(svc.insight(b64(raw if raw is not None else jpeg(512, 288)), prompt, ctx))


# ── reading a size without decoding ──────────────────────────────────────────


class TestImageDimensions:
    """Decoding an image to find out it is too big is the attack, not the defence."""

    def test_png_header(self):
        assert image_dimensions(png(512, 288)) == (512, 288)

    def test_jpeg_header(self):
        assert image_dimensions(jpeg(512, 288)) == (512, 288)

    def test_several_segments_before_the_frame_header(self):
        raw = jpeg(640, 360)
        comment = b"\xff\xfe" + struct.pack(">H", 20) + b"x" * 18
        assert image_dimensions(raw[:2] + comment + raw[2:]) == (640, 360)

    def test_restart_markers_carry_no_length_and_are_skipped(self):
        # Misreading one as a length is how a header walker wanders off the end.
        raw = jpeg(320, 240)
        assert image_dimensions(raw[:2] + b"\xff\xd0" + raw[2:]) == (320, 240)

    def test_anything_that_is_not_a_jpeg_or_png_is_none_rather_than_a_guess(self):
        assert image_dimensions(b"GIF89a" + b"\x00" * 40) is None
        assert image_dimensions(b"") is None
        assert image_dimensions(b"\xff\xd8" + b"\x00" * 30) is None

    def test_a_truncated_jpeg_terminates(self):
        assert image_dimensions(b"\xff\xd8\xff\xe0\x00\x10" + b"\x00" * 20) is None

    def test_a_huge_declared_size_costs_nothing_to_reject(self):
        # 20000x20000 as a header is under a hundred bytes. Decoded it is 1.6 GB.
        raw = png(20000, 20000)
        assert len(raw) < 100
        assert image_dimensions(raw) == (20000, 20000)

class TestSizeCap:
    def test_a_frame_within_the_cap_decodes(self):
        assert decode_frame(b64(jpeg(512, 288)), 768) == jpeg(512, 288)

    def test_the_long_edge_is_what_is_capped(self):
        # A 768x100 frame is within the cap; a 100x769 one is not, whichever way up it is.
        assert decode_frame(b64(jpeg(768, 100)), 768)
        with pytest.raises(VisionError) as raised:
            decode_frame(b64(jpeg(100, 769)), 768)
        assert raised.value.code == "frame_too_large"

    def test_the_client_already_capped_it_so_an_oversize_frame_is_refused_not_resized(self):
        # The client caps at 512 (§6.2). A frame over the server's own 768 means the client
        # is wrong, compromised, or not the client — none of which is fixed by a resize.
        with pytest.raises(VisionError) as raised:
            decode_frame(b64(png(4000, 3000)), 768)
        assert "4000x3000" in raised.value.detail

    def test_the_cap_comes_from_config_rather_than_a_constant(self):
        assert decode_frame(b64(jpeg(900, 500)), 1024)
        with pytest.raises(VisionError):
            decode_frame(b64(jpeg(900, 500)), 768)

    def test_an_enormous_body_is_refused_before_it_is_decoded(self):
        with pytest.raises(VisionError) as raised:
            decode_frame("A" * (MAX_BODY_BYTES + 1), 768)
        assert raised.value.code == "frame_too_large"

    def test_a_data_uri_prefix_is_accepted_as_well_as_raw_base64(self):
        assert decode_frame("data:image/jpeg;base64," + b64(jpeg(320, 180)), 768) == jpeg(320, 180)

    def test_rubbish_is_refused_by_name(self):
        for value, code in [
            ("", "bad_frame"),
            (None, "bad_frame"),
            ("not base64!!!", "bad_frame"),
            (b64(b"GIF89a" + b"\x00" * 40), "bad_frame"),
        ]:
            with pytest.raises(VisionError) as raised:
                decode_frame(value, 768)
            assert raised.value.code == code, value


# ── the answer ───────────────────────────────────────────────────────────────


class TestInsight:
    def test_prose_comes_back_as_text(self):
        result = insight(service("That y-axis starts at 40, which flatters the trend."))
        assert result["text"] == "That y-axis starts at 40, which flatters the trend."
        assert result["intents"] == []

    def test_a_tag_becomes_an_intent_and_leaves_the_speech(self):
        result = insight(service("[[emote:thinking 0.5]] That axis is doing some work."))
        assert result["text"] == "That axis is doing some work."
        assert result["intents"] == [{"name": "thinking", "intensity": 0.5}]

    def test_the_whitelist_is_checked_here_as_well_as_on_the_client(self):
        # Belt and braces (§6.9). The model is not a trusted source of gesture names.
        result = insight(service("[[emote:undress 1.0]] Interesting."))
        assert result["intents"] == []
        assert result["text"] == "Interesting."
        assert "emote" not in result["text"]

    def test_it_is_the_same_whitelist_the_protocol_uses(self):
        for name in list(EMOTE_WHITELIST)[:6]:
            result = insight(service(f"[[emote:{name}]] ok"))
            assert result["intents"][0]["name"] == name, name

    def test_at_most_one_gesture_survives(self):
        # §6.8 allows one tag per sentence of speech; a model sending five is ignoring its
        # instructions, and the first is the one it meant.
        result = insight(service("[[emote:happy]] a [[emote:sad]] b [[emote:angry]] c"))
        assert len(result["intents"]) == 1
        assert result["intents"][0]["name"] == "happy"

    def test_the_prompt_the_user_typed_reaches_the_model(self):
        svc = service()
        insight(svc, prompt="what do you think of this?")
        assert "what do you think of this?" in svc.calls[0]["user_prompt"]

    def test_the_context_reaches_it_too(self):
        svc = service()
        insight(svc, ctx={"activity": "watch", "scene": "ocean"})
        assert "watch" in svc.calls[0]["user_prompt"]
        assert "ocean" in svc.calls[0]["user_prompt"]

    def test_the_configured_model_is_the_one_asked(self):
        svc = service(cfg=config(model="gemma3:4b"))
        insight(svc)
        assert svc.calls[0]["model"] == "gemma3:4b"

    def test_the_model_is_given_bytes_never_a_path(self):
        svc = service()
        insight(svc)
        assert set(svc.calls[0]) == {"image_b64", "model", "user_prompt"}
        assert base64.b64decode(svc.calls[0]["image_b64"]) == jpeg(512, 288)

    def test_a_model_that_fails_is_a_refusal_not_a_crash(self):
        with pytest.raises(VisionError) as raised:
            insight(service(fail=RuntimeError("connection refused")))
        assert raised.value.code == "model_failed"

    def test_a_model_that_answers_not_ok_is_also_a_refusal(self):
        with pytest.raises(VisionError) as raised:
            insight(service(answer=None))
        assert raised.value.code == "model_failed"

    def test_the_oversize_check_happens_before_the_model_is_called(self):
        svc = service()
        with pytest.raises(VisionError):
            asyncio.run(svc.insight(b64(png(4000, 3000))))
        assert svc.calls == []

    def test_it_counts_what_happened_without_keeping_what_it_saw(self):
        svc = service("[[emote:undress]] hm")
        insight(svc)
        assert svc.stats.asks == 1
        assert svc.stats.intents_dropped == 1
        assert svc.stats.last_latency_ms is not None
        # Nothing in the counters could hold a frame or an answer.
        assert not any(isinstance(v, (bytes, str)) for v in vars(svc.stats).values() if not isinstance(v, dict))


class TestInsightMessage:
    def test_it_matches_the_shared_fixture_shape(self):
        import json
        from pathlib import Path

        fixture = json.loads(
            (Path(__file__).resolve().parents[1] / "fixtures" / "protocol" / "s2c-vision_insight.json").read_text(
                encoding="utf-8"
            )
        )
        built = insight_message({"text": "hi", "intents": [{"name": "thinking", "intensity": 0.5}]}, "f123")
        assert sorted(built) == sorted(fixture["required"])
        assert built["type"] == "vision_insight"
        assert built["frameId"] == "f123"


# ── the socket side ──────────────────────────────────────────────────────────


class TestVisionAsk:
    def paired(self, **kwargs):
        handler = ProtocolHandler(**kwargs)
        handler.handle({"v": 1, "type": "hello", "auth": "t", "client": "3dac", "caps": []})
        return handler

    def test_with_vision_off_it_is_refused_by_name(self):
        handler = self.paired()
        out = handler.handle({"v": 1, "type": "vision_ask", "prompt": "?", "frameId": "f1"})
        assert out[0]["code"] == "vision_unavailable"

    def test_without_client_consent_it_is_refused_before_anything_else(self):
        # §6.14: a server-side permission is not the same as the user having opted in on
        # the device holding the screen, so the consent answer comes first.
        handler = self.paired(vision=service())
        out = handler.handle({"v": 1, "type": "vision_ask", "prompt": "?", "frameId": "f1"})
        assert out[0]["code"] == "vision_no_consent"

    def test_with_consent_it_names_the_endpoint_that_takes_frames(self):
        # B10 shipped transcript mode rather than WebRTC, so this session has no data
        # channel and no frame can arrive over it. Saying so beats accepting an ask that
        # can never be answered.
        handler = self.paired(vision=service())
        handler.handle({"v": 1, "type": "user_event", "name": "capture:start"})
        out = handler.handle({"v": 1, "type": "vision_ask", "prompt": "?", "frameId": "f1"})
        assert out[0]["code"] == "vision_use_endpoint"
        assert "/avatar/vision/insight" in out[0]["msg"]

    def test_consent_starts_and_stops_from_the_client_events_b11_already_sends(self):
        handler = self.paired(vision=service())
        assert handler.state.capture_consent is False
        handler.handle({"v": 1, "type": "user_event", "name": "capture:start"})
        assert handler.state.capture_consent is True
        handler.handle({"v": 1, "type": "user_event", "name": "capture:stop"})
        assert handler.state.capture_consent is False
        # And revoking mid-session closes the door again.
        assert handler.handle({"v": 1, "type": "vision_ask", "prompt": "?"})[0]["code"] == "vision_no_consent"

    def test_the_handler_holds_no_frame_at_any_point(self):
        handler = self.paired(vision=service())
        handler.handle({"v": 1, "type": "user_event", "name": "capture:start"})
        handler.handle({"v": 1, "type": "vision_ask", "prompt": "?", "frameId": "f1"})
        held = repr(vars(handler)) + repr(vars(handler.state))
        assert "image_b64" not in held
        assert "frame" not in held.replace("frames", "")


class TestOverhead:
    """§9 targets p95 ≤3 s for the round trip. Almost all of that is the model, which is a
    deployment's hardware and not something a test runner can speak for. What *is* this
    module's to answer for is the work either side of the model call — decode, size check,
    tag split — and that is what is measured here. A regression that made the wrapper cost
    a meaningful slice of the budget would show up; the model's own latency would not, and
    the test says so rather than implying otherwise."""

    def test_the_wrapper_costs_a_rounding_error_of_the_budget(self):
        import time

        svc = service()
        raw = jpeg(512, 288)
        encoded = b64(raw)

        # Warm, then measure the floor: what the code can do, not what the box is doing.
        for _ in range(5):
            asyncio.run(svc.insight(encoded))

        best = float("inf")
        for _ in range(5):
            started = time.perf_counter()
            for _ in range(50):
                asyncio.run(svc.insight(encoded))
            best = min(best, (time.perf_counter() - started) / 50)

        # 3000 ms is the whole round trip. A hundredth of it for everything that is not the
        # model leaves the budget where it belongs.
        assert best < 0.03, f"{best * 1000:.2f} ms of overhead per ask"

    def test_the_size_check_does_not_get_slower_with_the_image(self):
        # The whole point of reading the header: a 20000x20000 declaration costs what a
        # 512x288 one costs, because neither is decoded.
        import time

        small = b64(jpeg(512, 288))
        huge = b64(png(20000, 20000))

        def cost(value):
            best = float("inf")
            for _ in range(5):
                started = time.perf_counter()
                for _ in range(200):
                    try:
                        decode_frame(value, 768)
                    except VisionError:
                        pass
                best = min(best, (time.perf_counter() - started) / 200)
            return best

        assert cost(huge) < cost(small) * 5


class TestMounting:
    def test_no_model_configured_means_no_route_at_all(self, monkeypatch):
        # A route that answers every request "not configured" looks like a feature to
        # anything probing the API surface. Better not to have one.
        from app.avatar_director.session import vision_service

        assert vision_service(AvatarDirectorConfig(enabled=True)) is None
        assert vision_service(config()) is not None

    def test_the_service_reads_the_cap_from_config(self):
        assert VisionService(config(max_px=512)).max_px == 512
        assert VisionService(config()).max_px == 768
