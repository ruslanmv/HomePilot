"""One place every image passes through (batch V4).

This batch changes no behaviour, and that is the claim under test. The seam exists so that V5
changes one file rather than four call sites, and so that the six failure modes in the plan
have somewhere to be told apart — until now "the model returned nothing", "the image was forty
megapixels" and "the resize destroyed the text" all arrived as the same silence.

Two properties carry it:

* **the bytes are unchanged.** A seam that starts altering images on the day it lands is not a
  seam, it is V5 arriving early and unannounced;
* **both paths meet at it.** The `image_b64` route used to run right through to the request
  without touching `_load_image_bytes`, which is how `meta.image_size_bytes` came to report 0
  for every avatar-director and remote-screenshot analysis: there was no one place, so the fix
  had to be made twice.
"""

from __future__ import annotations

import asyncio
import base64
import io

import pytest

from app import multimodal as mm
from app import vision_adapter


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def png(width=32, height=16, mode="RGB"):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new(mode, (width, height), (10, 20, 30) if mode == "RGB" else 0).save(buffer, format="PNG")
    return buffer.getvalue()


# ── the adapter alone ───────────────────────────────────────────────────────


def test_it_hands_back_exactly_what_it_was_given():
    data = png()
    out = vision_adapter.adapt(data, mime_type="image/png")
    assert out.data == data
    assert out.strategy == "passthrough"
    assert out.scale == 1.0
    assert out.tiles == 1


def test_it_measures_what_it_passed_through():
    out = vision_adapter.adapt(png(width=1280, height=653))
    assert (out.width, out.height) == (1280, 653)
    assert (out.original_width, out.original_height) == (1280, 653)
    assert out.original_bytes == out.meta()["bytes"]


def test_a_sniffed_type_beats_a_declared_one():
    # `/upload` maps mime by file extension, and an extension is what somebody typed.
    out = vision_adapter.adapt(png(), mime_type="image/jpeg")
    assert out.mime_type == "image/png"


def test_an_unreadable_image_is_passed_through_and_said_so():
    # A vision request must not fail because an optional measurement could not be taken.
    out = vision_adapter.adapt(b"not an image at all")
    assert out.data == b"not an image at all"
    assert out.width is None
    assert "unmeasured" in out.warnings


def test_nothing_at_all_is_recorded_rather_than_raised():
    out = vision_adapter.adapt(b"")
    assert out.data == b""
    assert "empty" in out.warnings


def test_a_purpose_nobody_has_heard_of_is_recorded_not_refused():
    # An unknown purpose is a caller that has not been updated. Refusing its image would
    # break a working feature over a label.
    out = vision_adapter.adapt(png(), purpose="interpretive-dance")
    assert out.data
    assert any(w.startswith("unknown-purpose") for w in out.warnings)


def test_a_very_large_image_is_still_passed_through_in_v4():
    # V5 resizes. V4 measuring it and doing nothing is the point of landing the seam first.
    out = vision_adapter.adapt(png(width=4000, height=2000))
    assert out.strategy == "passthrough"
    assert out.width == 4000
    assert not out.warnings


# ── both paths meet at it ───────────────────────────────────────────────────


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _ollama(monkeypatch, seen):
    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kwargs):
            seen.update(kwargs.get("json") or {})
            return _Response({"message": {"content": "A small blue rectangle, plainly."}})

    monkeypatch.setattr(mm.httpx, "AsyncClient", Client)


def test_the_base64_path_reports_the_real_byte_count(monkeypatch, tmp_path):
    # It reported 0 before V3, then an estimate, and now the measured number — because the
    # bytes are decoded before they reach the adapter rather than after the response.
    seen = {}
    _ollama(monkeypatch, seen)
    data = png(width=64, height=64)
    out = run(
        mm.analyze_image_ollama(
            "", tmp_path, model="gemma3:4b", image_b64=base64.b64encode(data).decode("ascii")
        )
    )
    assert out["ok"] is True
    assert out["meta"]["image_size_bytes"] == len(data)


def test_the_base64_path_is_measured_like_any_other(monkeypatch, tmp_path):
    seen = {}
    _ollama(monkeypatch, seen)
    out = run(
        mm.analyze_image_ollama(
            "", tmp_path, model="gemma3:4b", image_b64=base64.b64encode(png(64, 32)).decode("ascii")
        )
    )
    adapter = out["meta"]["adapter"]
    assert (adapter["width"], adapter["height"]) == (64, 32)
    assert adapter["strategy"] == "passthrough"


def test_the_bytes_the_model_receives_are_the_bytes_it_was_given(monkeypatch, tmp_path):
    # The whole "behaviour identical" claim, asserted where it matters: at the wire.
    seen = {}
    _ollama(monkeypatch, seen)
    data = png(48, 24)
    encoded = base64.b64encode(data).decode("ascii")
    run(mm.analyze_image_ollama("", tmp_path, model="gemma3:4b", image_b64=encoded))
    assert seen["messages"][1]["images"] == [encoded]


def test_the_file_path_is_adapted_too(monkeypatch, tmp_path):
    seen = {}
    _ollama(monkeypatch, seen)
    data = png(100, 50)
    (tmp_path / "shot.png").write_bytes(data)
    out = run(mm.analyze_image_ollama("/files/shot.png", tmp_path, model="gemma3:4b"))
    assert out["meta"]["adapter"]["width"] == 100
    assert out["meta"]["image_size_bytes"] == len(data)


def test_an_empty_generation_still_reports_what_the_adapter_saw(monkeypatch, tmp_path):
    # V3's typed failure and V4's measurement have to arrive together, or "the model said
    # nothing" and "the image was unreadable" stay the same shrug.
    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kwargs):
            return _Response({"message": {"content": "   "}})

    monkeypatch.setattr(mm.httpx, "AsyncClient", Client)
    out = run(
        mm.analyze_image_ollama(
            "", tmp_path, model="moondream:latest", image_b64=base64.b64encode(png(1000, 500)).decode("ascii")
        )
    )
    assert out["error_code"] == "empty_model_response"
    assert out["meta"]["adapter"]["width"] == 1000
