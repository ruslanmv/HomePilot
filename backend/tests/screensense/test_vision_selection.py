"""Which vision model reads your screen, and what happens when it says nothing (V1–V3).

Three defects, each of which made the product look like a weak model when it was not:

* **V1 — the user's choice never reached the request.** Settings has always stored a
  multimodal model and ``/v1/multimodal/analyze`` has always accepted one; nothing carried it
  between them, so the backend auto-detected instead. Somebody with a good model selected got
  whichever model detection found.
* **V2 — detection returned the first installed match** in Ollama's own ``/api/tags`` order,
  roughly by modification time. Which model read your screen depended on which one you last
  pulled. The tempting fix — reordering ``VISION_MODEL_PATTERNS`` — changes nothing, and there
  is a test here that fails if somebody tries it.
* **V3 — an empty generation was reported as success.** ``ok: True`` with an empty string left
  the browser's own filter as the only thing between the user and noise, at the last possible
  moment, with no layer able to retry because the call had been declared a success.
"""

from __future__ import annotations

import asyncio

import pytest

from app import multimodal as mm
from app.screensense import routes


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _frames_in_tmp(tmp_path, monkeypatch):
    """Keep captured frames out of the repository's own upload directory."""
    from app.screensense import config, frames

    monkeypatch.setattr(config, "frames_dir", lambda: tmp_path / "screensense")
    (tmp_path / "screensense").mkdir(parents=True, exist_ok=True)
    frames.reset()
    yield
    frames.reset()


# ── V2: ranking ─────────────────────────────────────────────────────────────


def test_a_better_model_wins_however_ollama_orders_them():
    # Ollama lists roughly by modification time, so the adversarial case is the good model
    # listed last — which is exactly what "first match" got wrong.
    assert mm.best_vision_model(["moondream:latest", "llava:7b", "qwen3-vl:8b"]) == "qwen3-vl:8b"
    assert mm.best_vision_model(["qwen3-vl:8b", "moondream:latest"]) == "qwen3-vl:8b"


def test_moondream_is_chosen_only_when_it_is_the_only_one():
    assert mm.best_vision_model(["moondream:latest"]) == "moondream:latest"
    assert mm.best_vision_model(["moondream:latest", "gemma3:4b"]) == "gemma3:4b"


def test_reordering_the_membership_list_does_not_change_the_choice(monkeypatch):
    # The obvious guess is that Moondream wins because it is first in VISION_MODEL_PATTERNS.
    # It is not, and a batch spent reordering that list would change nothing — so this test
    # fails if the ranking is ever made to depend on it.
    monkeypatch.setattr(mm, "VISION_MODEL_PATTERNS", list(reversed(mm.VISION_MODEL_PATTERNS)))
    assert mm.best_vision_model(["moondream:latest", "qwen3-vl:8b"]) == "qwen3-vl:8b"


def test_a_vision_family_nobody_ranked_still_beats_the_last_resort(monkeypatch):
    monkeypatch.setattr(mm, "VISION_MODEL_PATTERNS", mm.VISION_MODEL_PATTERNS + ["newvlm"])
    assert mm.best_vision_model(["moondream:latest", "newvlm:8b"]) == "newvlm:8b"


def test_qwen2_5_vl_is_recognised_at_all():
    # The repo's own catalog ships `qwen2.5vl:7b`, and neither `qwen3-vl` nor `qwen2-vl` is a
    # substring of it — so before V2 that model was classified as not a vision model, was
    # invisible to detection, and was filtered out of /models.
    assert mm.is_vision_model("qwen2.5vl:7b") is True
    assert mm.best_vision_model(["moondream:latest", "qwen2.5vl:7b"]) == "qwen2.5vl:7b"


def test_a_model_that_is_not_a_vision_model_is_never_chosen():
    assert mm.best_vision_model(["llama3:8b", "mistral:7b"]) is None
    assert mm.best_vision_model([]) is None


def test_ties_keep_the_order_ollama_gave_them():
    assert mm.best_vision_model(["llava:7b", "llava:13b"]) == "llava:7b"


# ── V3: an empty answer ─────────────────────────────────────────────────────


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _ollama(monkeypatch, payload):
    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kwargs):
            return _Response(payload)

    monkeypatch.setattr(mm.httpx, "AsyncClient", Client)


def test_an_empty_generation_is_a_typed_failure(monkeypatch):
    _ollama(monkeypatch, {"message": {"content": "   "}})
    out = run(mm.analyze_image_ollama("", None, model="moondream:latest", image_b64="Zm9v"))
    assert out["ok"] is False
    assert out["error_code"] == "empty_model_response"
    # `error` stays a human-readable string, so every existing caller keeps working.
    assert isinstance(out["error"], str) and "moondream:latest" in out["error"]


def test_a_real_answer_is_still_a_success(monkeypatch):
    _ollama(monkeypatch, {"message": {"content": "  A code editor with a traceback.  "}})
    out = run(mm.analyze_image_ollama("", None, model="gemma3:4b", image_b64="Zm9v"))
    assert out["ok"] is True
    assert out["analysis_text"] == "A code editor with a traceback."


def test_the_reported_image_size_is_not_zero_on_the_base64_path(monkeypatch):
    # `raw_bytes` is empty when the caller hands in an encoded image, so this used to report
    # 0 bytes for every avatar-director and remote-screenshot analysis.
    _ollama(monkeypatch, {"message": {"content": "A window with some text in it."}})
    out = run(mm.analyze_image_ollama("", None, model="gemma3:4b", image_b64="A" * 400))
    assert out["meta"]["image_size_bytes"] == 300


# ── V1: the third call site ─────────────────────────────────────────────────


def test_explain_uses_this_machines_configured_model(monkeypatch):
    # RS1's caller is a browser on somebody else's machine and cannot know this HomePilot's
    # Settings — its localStorage belongs to a different install. The environment is the
    # honest server-side equivalent.
    monkeypatch.setenv("MULTIMODAL_MODEL", "gemma3:4b")
    monkeypatch.setenv("MULTIMODAL_BASE_URL", "http://vision.local:11434")
    seen = {}

    async def fake_analyze(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "analysis_text": "An editor.", "meta": {"model": kwargs.get("model")}}

    monkeypatch.setattr(mm, "analyze_image", fake_analyze)
    from app.screensense import frames

    frame = frames.store(b"\xff\xd8jpeg", "share")
    run(routes.explain(routes.ExplainIn(frame_id=frame.frame_id, question="what is this?")))
    assert seen["model"] == "gemma3:4b"
    assert seen["base_url"] == "http://vision.local:11434"
    frames.drop(frame.frame_id)


def test_an_explicit_model_still_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv("MULTIMODAL_MODEL", "gemma3:4b")
    seen = {}

    async def fake_analyze(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "analysis_text": "An editor.", "meta": {}}

    monkeypatch.setattr(mm, "analyze_image", fake_analyze)
    from app.screensense import frames

    frame = frames.store(b"\xff\xd8jpeg", "share")
    run(routes.explain(routes.ExplainIn(frame_id=frame.frame_id, question="?", model="qwen3-vl:8b")))
    assert seen["model"] == "qwen3-vl:8b"
    frames.drop(frame.frame_id)


def test_no_configured_model_falls_through_to_detection(monkeypatch):
    # An unset variable must mean "auto", not a model named "".
    monkeypatch.delenv("MULTIMODAL_MODEL", raising=False)
    monkeypatch.delenv("MULTIMODAL_BASE_URL", raising=False)
    seen = {}

    async def fake_analyze(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "analysis_text": "An editor.", "meta": {}}

    monkeypatch.setattr(mm, "analyze_image", fake_analyze)
    from app.screensense import frames

    frame = frames.store(b"\xff\xd8jpeg", "share")
    run(routes.explain(routes.ExplainIn(frame_id=frame.frame_id, question="?")))
    assert seen["model"] == ""
    assert seen["base_url"] == ""
    frames.drop(frame.frame_id)


def test_explain_turns_an_empty_answer_into_a_sentence_about_the_screenshot(monkeypatch):
    async def fake_analyze(**kwargs):
        return {
            "ok": False,
            "error_code": "empty_model_response",
            "error": "moondream:latest returned no description of the image.",
            "analysis_text": "",
            "meta": {"model": "moondream:latest"},
        }

    monkeypatch.setattr(mm, "analyze_image", fake_analyze)
    from app.screensense import frames

    frame = frames.store(b"\xff\xd8jpeg", "share")
    response = run(routes.explain(routes.ExplainIn(frame_id=frame.frame_id, question="?")))
    body = response.body.decode()
    assert "empty_model_response" in body
    # The capture worked and the card is still on screen; the sentence says which half failed.
    assert "took the screenshot" in body
    frames.drop(frame.frame_id)
