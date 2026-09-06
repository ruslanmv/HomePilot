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
import importlib

import pytest

from app import multimodal as mm
from app.screensense import routes


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _live_modules():
    """Re-bind `mm` and `routes` to whatever is in ``sys.modules`` right now.

    ``conftest._load_app()`` purges every ``app*`` module and re-imports the backend so that a
    test's environment overrides are seen at import time. That is deliberate and load-bearing —
    but it means a module object captured at *collection* time is stale afterwards, and
    ``monkeypatch.setattr(mm, "analyze_image", ...)`` then patches an object nothing calls: the
    route's own lazy import reads ``sys.modules["app.multimodal"]``, which is the new one.

    The symptom was four tests here that passed alone and failed whenever a file requesting the
    session-scoped ``client`` fixture ran first — invisible under alphabetical ordering, and a
    coin flip under random ordering. Re-resolving per test costs nothing and makes this file
    independent of what ran before it.
    """
    global mm, routes
    mm = importlib.import_module("app.multimodal")
    routes = importlib.import_module("app.screensense.routes")
    yield


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


def test_an_upload_with_no_text_asks_the_question_a_person_would(monkeypatch):
    """The half of the report that failed.

    An upload *with* "what you can see" was answered fine by `moondream:latest`. The same
    image with no text came back empty — and no-text is the path that builds its own prompt
    here. Small caption models are trained on visual question answering, and an imperative
    "Describe this image" is off that distribution in a way a question is not.
    """
    seen = {}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            seen.update(json)
            return _Response({"message": {"content": "A phone screen."}})

    monkeypatch.setattr(mm.httpx, "AsyncClient", Client)
    out = run(mm.analyze_image_ollama("", None, model="moondream:latest", image_b64="Zm9v"))

    assert out["ok"] is True
    assert seen["messages"][1]["content"].startswith("What can you see in this image?")
    # The OCR half of "both" has to survive the rewording, or a screenshot stops being read.
    assert "transcribe it exactly" in seen["messages"][1]["content"]


def test_a_typed_question_is_still_the_one_that_is_asked(monkeypatch):
    # The default is a fallback, never an override. Rewriting what somebody typed would be a
    # far worse bug than the one this fixes.
    seen = {}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            seen.update(json)
            return _Response({"message": {"content": "Yes."}})

    monkeypatch.setattr(mm.httpx, "AsyncClient", Client)
    run(
        mm.analyze_image_ollama(
            "", None, model="gemma3:4b", image_b64="Zm9v", user_prompt="is there a cat in this"
        )
    )
    assert seen["messages"][1]["content"] == "is there a cat in this"


def _two_models(post):
    """An Ollama with `moondream:latest` and `gemma3:4b` installed."""

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return _Response({"models": [{"name": "moondream:latest"}, {"name": "gemma3:4b"}]})

        async def post(self, url, json):
            return post(json)

    return Client


def test_an_empty_generation_falls_back_to_a_better_installed_model(monkeypatch):
    """The user has both installed and the weaker one says nothing.

    Answering with the model they also installed beats a red error in the chat, and it is
    the same remedy a stopped runner already gets — an empty generation is a fact about this
    model, not about the upload.
    """
    calls = []

    def post(json):
        calls.append(json["model"])
        content = "" if json["model"] == "moondream:latest" else "A portrait on a phone screen."
        return _Response({"message": {"content": content}})

    monkeypatch.setattr(mm.httpx, "AsyncClient", _two_models(post))
    out = run(mm.analyze_image_ollama("", None, model="moondream:latest", image_b64="Zm9v"))

    assert out["ok"] is True
    assert out["analysis_text"] == "A portrait on a phone screen."
    assert out["meta"]["model"] == "gemma3:4b"
    # Say which model answered and why the first one did not, or the meta names a model the
    # user never chose with no account of how it got there.
    assert out["meta"]["fallback_from"] == "moondream:latest"
    assert out["meta"]["fallback_reason"] == "empty_model_response"
    assert calls == ["moondream:latest", "gemma3:4b"]


def test_the_fallback_never_recurses(monkeypatch):
    """Every installed model failing must cost one extra call, not a walk of the list.

    This is the whole safety argument for the retry, and it is the one thing a reader cannot
    check by eye — so it is asserted by counting.
    """
    calls = []

    def post(json):
        calls.append(json["model"])
        return _Response({"message": {"content": ""}})

    monkeypatch.setattr(mm.httpx, "AsyncClient", _two_models(post))
    out = run(mm.analyze_image_ollama("", None, model="moondream:latest", image_b64="Zm9v"))

    assert out["ok"] is False
    assert out["error_code"] == "empty_model_response"
    assert calls == ["moondream:latest", "gemma3:4b"]


def test_the_guard_holds_even_when_the_best_model_changes_mid_request(monkeypatch):
    """The single-shot flag, on its own.

    Normally it is invisible: `_detect_best_vision_model` returns the same answer every time,
    so a second retry stops at "the fallback is the model that just failed". The flag only
    shows itself when that answer *moves* — a pull finishing between calls, a model being
    removed — and then it is the sole thing standing between one upload and a walk of the
    whole installed list. So the ranking is made to change on every call, deliberately.
    """
    calls = []
    catalog = [
        # Each answer must be strictly better than the model that just failed, or the
        # `fallback == failed_model` guard stops the walk and this proves nothing. Ranks
        # run moondream 12 → llava 8 → llama3.2-vision 6 → gemma3 5 → qwen2.5vl 1.
        [{"name": "moondream:latest"}, {"name": "llava:13b"}],
        [{"name": "llava:13b"}, {"name": "llama3.2-vision:11b"}],
        [{"name": "llama3.2-vision:11b"}, {"name": "gemma3:4b"}],
        [{"name": "gemma3:4b"}, {"name": "qwen2.5vl:7b"}],
    ]

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return _Response({"models": catalog.pop(0) if catalog else []})

        async def post(self, url, json):
            calls.append(json["model"])
            return _Response({"message": {"content": ""}})

    monkeypatch.setattr(mm.httpx, "AsyncClient", Client)
    out = run(mm.analyze_image_ollama("", None, model="moondream:latest", image_b64="Zm9v"))

    assert out["ok"] is False
    # Exactly one retry. Never a third call, however tempting the next-best model looks.
    assert len(calls) == 2, f"expected one retry, walked {calls}"


def test_the_best_installed_model_returning_nothing_is_not_retried(monkeypatch):
    # Already the best choice: there is nothing better to try, so the typed failure stands
    # rather than the same model being asked twice.
    calls = []

    def post(json):
        calls.append(json["model"])
        return _Response({"message": {"content": ""}})

    monkeypatch.setattr(mm.httpx, "AsyncClient", _two_models(post))
    out = run(mm.analyze_image_ollama("", None, model="gemma3:4b", image_b64="Zm9v"))

    assert out["ok"] is False
    assert calls == ["gemma3:4b"]


def test_a_real_answer_is_still_a_success(monkeypatch):
    _ollama(monkeypatch, {"message": {"content": "  A code editor with a traceback.  "}})
    out = run(mm.analyze_image_ollama("", None, model="gemma3:4b", image_b64="Zm9v"))
    assert out["ok"] is True
    assert out["analysis_text"] == "A code editor with a traceback."


def test_a_stopped_ollama_runner_falls_back_to_another_installed_model(monkeypatch):
    calls = []

    class Response(_Response):
        text = ""

        def __init__(self, payload, status_code=200, text=""):
            super().__init__(payload)
            self.status_code = status_code
            self.text = text

        def raise_for_status(self):
            if self.status_code >= 400:
                request = mm.httpx.Request("POST", "http://ollama/api/chat")
                response = mm.httpx.Response(self.status_code, request=request, text=self.text)
                raise mm.httpx.HTTPStatusError("runner stopped", request=request, response=response)

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return Response({"models": [{"name": "moondream:latest"}, {"name": "gemma3:4b"}]})

        async def post(self, url, json):
            calls.append(json["model"])
            if json["model"] == "moondream:latest":
                return Response(
                    {},
                    500,
                    '{"error":"model runner has unexpectedly stopped, this may be due to resource limitations"}',
                )
            return Response({"message": {"content": "A settings window."}})

    monkeypatch.setattr(mm.httpx, "AsyncClient", Client)
    out = run(mm.analyze_image_ollama("", None, model="moondream:latest", image_b64="Zm9v"))

    assert out["ok"] is True
    assert out["analysis_text"] == "A settings window."
    assert out["meta"]["model"] == "gemma3:4b"
    assert out["meta"]["fallback_from"] == "moondream:latest"
    assert calls == ["moondream:latest", "gemma3:4b"]


def test_a_stopped_runner_returns_an_actionable_typed_error_without_an_alternative(monkeypatch):
    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return _Response({"models": [{"name": "moondream:latest"}]})

        async def post(self, url, json):
            request = mm.httpx.Request("POST", url)
            response = mm.httpx.Response(
                500,
                request=request,
                text='{"error":"model runner has unexpectedly stopped"}',
            )
            raise mm.httpx.HTTPStatusError("runner stopped", request=request, response=response)

    monkeypatch.setattr(mm.httpx, "AsyncClient", Client)
    out = run(mm.analyze_image_ollama("", None, model="moondream:latest", image_b64="Zm9v"))

    assert out["ok"] is False
    assert out["error_code"] == "model_runner_stopped"
    assert "RAM or VRAM" in out["error"]


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
