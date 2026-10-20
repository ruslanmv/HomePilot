"""Images through an OpenAI-compatible endpoint (an OllaBridge gateway), and the vision check.

`multimodal.analyze_image` spoke only Ollama's own API; every other provider was answered
"not supported", so a vision model behind an OllaBridge gateway could never be used for image
input. The OpenAI-compatible provider sends the image the standard way — a text part and an
``image_url`` data URI — and `vision_check` verifies, with a known test image, that a model
really sees before Models → Multimodal offers it.
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
from pathlib import Path

import httpx
import pytest


def _modules():
    return importlib.import_module("app.multimodal"), importlib.import_module("app.vision_check")


def _mock(monkeypatch, multimodal, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(multimodal.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def _answer(text):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": text}}]})


BASE = "http://localhost:11435/v1"
MODEL = "openwebui/internal-gemma4-31b"


def _analyze(multimodal, vision_check, **kw):
    return asyncio.run(multimodal.analyze_image(
        "", Path("."), provider="openai_compat", base_url=BASE, model=MODEL,
        image_b64=base64.b64encode(vision_check.test_image_png()).decode(), **kw,
    ))


class TestTheOpenAICompatibleProvider:
    def test_the_image_travels_as_an_openai_image_part(self, monkeypatch):
        multimodal, vision_check = _modules()
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("authorization")
            seen["body"] = json.loads(request.content)
            return _answer("A yellow and blue rectangle.")

        _mock(monkeypatch, multimodal, handler)
        result = _analyze(multimodal, vision_check, user_prompt="What is this?", api_key="gw-key")

        assert result["ok"] is True
        assert result["analysis_text"] == "A yellow and blue rectangle."
        assert seen["url"] == f"{BASE}/chat/completions"
        assert seen["auth"] == "Bearer gw-key"
        user = seen["body"]["messages"][1]
        assert user["content"][0] == {"type": "text", "text": "What is this?"}
        image = user["content"][1]
        assert image["type"] == "image_url"
        # The bytes are a PNG and the data URI says so — not the JPEG label inline images get.
        assert image["image_url"]["url"].startswith("data:image/")
        assert seen["body"]["model"] == MODEL

    def test_a_route_that_cannot_carry_images_says_so(self, monkeypatch):
        multimodal, vision_check = _modules()

        def handler(request):
            return httpx.Response(501, json={"detail": {"error": {
                "message": "Model 'x' is served through the 'relay_link' route, which cannot carry images yet.",
                "type": "unsupported_capability"}}})

        _mock(monkeypatch, multimodal, handler)
        result = _analyze(multimodal, vision_check)
        assert result["ok"] is False
        assert result["error_code"] == "images_not_supported"
        assert "cannot carry images" in result["error"]

    def test_no_model_is_a_clear_error_not_a_request(self, monkeypatch):
        multimodal, _ = _modules()

        def handler(request):  # pragma: no cover — must not be called
            raise AssertionError("no request without a model")

        _mock(monkeypatch, multimodal, handler)
        result = asyncio.run(multimodal.analyze_image("", Path("."), provider="openai_compat",
                                                      base_url=BASE, model="", image_b64="AAAA"))
        assert result["error_code"] == "no_model"

    def test_ollama_is_still_answered_by_the_ollama_path(self, monkeypatch):
        multimodal, _ = _modules()
        called = {}

        async def fake_ollama(*args, **kwargs):
            called["yes"] = True
            return {"ok": True, "analysis_text": "x", "meta": {}}

        monkeypatch.setattr(multimodal, "analyze_image_ollama", fake_ollama)
        asyncio.run(multimodal.analyze_image("", Path("."), provider="ollama", model="llava", image_b64="AAAA"))
        assert called == {"yes": True}


class TestTheVisionCheck:
    @pytest.mark.parametrize("answer,sees", [
        ("LEFT=yellow, RIGHT=blue", True),
        ("The left half is yellow and the right half is blue.", True),
        ("LEFT=amarillo, RIGHT=azul", True),
        ("NO IMAGE", False),
        ("LEFT=blue, RIGHT=yellow", False),     # wrong order is a guess, not sight
        ("I think it's red.", False),
    ])
    def test_the_verdict(self, answer, sees):
        _, vision_check = _modules()
        assert vision_check.judge(answer) is sees

    def test_a_model_that_sees_passes(self, monkeypatch):
        multimodal, vision_check = _modules()
        _mock(monkeypatch, multimodal, lambda request: _answer("LEFT=yellow, RIGHT=blue"))
        result = asyncio.run(vision_check.check(provider="openai_compat", base_url=BASE, model=MODEL))
        assert result["sees_images"] is True

    def test_a_model_that_was_never_shown_the_image_fails(self, monkeypatch):
        # Exactly what the gateway did before it kept images: the model answered blind.
        multimodal, vision_check = _modules()
        _mock(monkeypatch, multimodal, lambda request: _answer("NO IMAGE"))
        result = asyncio.run(vision_check.check(provider="openai_compat", base_url=BASE, model=MODEL))
        assert result["sees_images"] is False
        assert "cannot see images" in result["reason"]

    def test_the_test_image_is_a_real_png(self):
        _, vision_check = _modules()
        png = vision_check.test_image_png()
        assert png.startswith(b"\x89PNG\r\n\x1a\n") and len(png) < 2048
