"""
The hosted web edition runs on Hugging Face by default and must keep working when it fails:

  * chat goes to Hugging Face first and falls back to the local Ollama model when Hugging Face
    cannot answer (no token, out of credits, rate limited, every model down);
  * a model that is down falls through to the next default; an account problem does not
    (the next model would fail the same way);
  * images and video go to Hugging Face whenever ComfyUI is not configured, instead of
    "Image generation is not configured on this server";
  * the Space's own token serves visitors without a linked account — never on a local install;
  * a local install keeps its providers exactly as before.
"""
from __future__ import annotations

import sys
import uuid

import httpx
import pytest


def _hf():
    return sys.modules["app.connectors.huggingface"]


def _user(client):
    r = client.post("/v1/auth/register", json={"username": f"r{uuid.uuid4().hex[:10]}"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def web(monkeypatch):
    config = sys.modules["app.config"]
    monkeypatch.setattr(config, "HOMEPILOT_EDITION", "web")
    monkeypatch.setattr(config, "COMFY_BASE_URL", "")
    monkeypatch.setenv("HOMEPILOT_HF_TOKEN", "hf_space_token_123")


@pytest.fixture
def local(monkeypatch):
    config = sys.modules["app.config"]
    monkeypatch.setattr(config, "HOMEPILOT_EDITION", "local")
    monkeypatch.setenv("HOMEPILOT_HF_TOKEN", "hf_space_token_123")


def _status_error(code):
    req = httpx.Request("POST", "https://router.huggingface.co/v1/chat/completions")
    return httpx.HTTPStatusError(f"{code}", request=req, response=httpx.Response(code, request=req))


def _chat(client, h, **extra):
    body = {"message": "hello", "mode": "chat", "provider": "huggingface",
            "provider_model": "meta-llama/Llama-3.1-8B-Instruct",
            "conversation_id": f"res-{uuid.uuid4().hex[:6]}", **extra}
    r = client.post("/chat", headers=h, json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ── defaults ─────────────────────────────────────────────────────────────────

def test_web_defaults_are_hugging_face_with_ollama_behind_chat(client, web):
    d = client.get("/auto-detect").json()
    assert d["providerChat"] == "huggingface" and "/" in d["modelChat"]
    assert d["providerImages"] == "huggingface" and d["modelImages"].startswith("hf:")
    assert d["providerVideo"] == "huggingface" and d["modelVideo"].startswith("hf:")
    assert d["providerMultimodal"] == "huggingface"
    assert d["detected"]["huggingface"]["chat_fallback"] == "ollama"


def test_local_defaults_are_unchanged(client, local):
    d = client.get("/auto-detect").json()
    assert d["providerChat"] == "ollama" and d["providerImages"] == "comfyui"
    assert d["providerVideo"] == "comfyui" and d["providerMultimodal"] == "ollama"


def test_the_space_token_is_never_used_on_a_local_install(local):
    assert _hf().shared_token() == ""


# ── chat ─────────────────────────────────────────────────────────────────────

def test_chat_falls_back_to_ollama_when_out_of_credits(client, web, mock_outbound, monkeypatch):
    llm = sys.modules["app.llm"]
    tried = []

    async def out_of_credits(messages, *, temperature, max_tokens, base_url, model, api_key=None):
        tried.append(model)
        raise _status_error(402)
    monkeypatch.setattr(llm, "chat_openai_compat", out_of_credits)
    data = _chat(client, _user(client))
    assert "mock-ollama" in data["text"]
    assert tried == ["meta-llama/Llama-3.1-8B-Instruct"]   # credits: the next model is not tried
    # The reply says the local model wrote it, and why — not passed off as Hugging Face.
    by = data["answered_by"]
    assert by["provider"] == "ollama" and by["fell_back"] is True
    assert by["reason"] == "Hugging Face credits ran out"


def test_chat_tries_the_next_model_when_one_is_down(client, web, mock_outbound, monkeypatch):
    llm = sys.modules["app.llm"]
    tried = []

    async def first_down(messages, *, temperature, max_tokens, base_url, model, api_key=None):
        tried.append(model)
        if len(tried) == 1:
            raise _status_error(404)
        assert api_key == "hf_space_token_123"            # the Space's own token
        return {"choices": [{"message": {"role": "assistant", "content": f"answer from {model}"}}]}
    monkeypatch.setattr(llm, "chat_openai_compat", first_down)
    data = _chat(client, _user(client), provider_model="some-org/retired-model")
    assert tried[0] == "some-org/retired-model" and len(tried) == 2
    assert data["text"] == f"answer from {tried[1]}"
    # The badge names the model of the chain that actually answered.
    assert data["answered_by"] == {"provider": "huggingface", "model": tried[1], "fell_back": False, "reason": None}


def test_chat_without_any_token_answers_with_ollama(client, web, mock_outbound, monkeypatch):
    monkeypatch.delenv("HOMEPILOT_HF_TOKEN")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    data = _chat(client, _user(client))
    assert "mock-ollama" in data["text"]
    assert data["answered_by"]["fell_back"] is True
    assert data["answered_by"]["reason"] == "Hugging Face is not connected"


# ── images ───────────────────────────────────────────────────────────────────

class _FakeClient:
    """InferenceClient stand-in: fails for the models in ``down`` with ``status``."""
    down: dict = {}
    calls: list = []

    def __init__(self, provider=None, token=None, timeout=None):
        _FakeClient.calls.append(("token", token))

    def text_to_image(self, prompt, *, model=None, **kw):
        _FakeClient.calls.append(("model", model))
        if model in _FakeClient.down:
            raise _status_error(_FakeClient.down[model])
        from PIL import Image
        return Image.new("RGB", (32, 32), "teal")


@pytest.fixture
def fake_hub(monkeypatch):
    import huggingface_hub
    _FakeClient.down, _FakeClient.calls = {}, []
    monkeypatch.setattr(huggingface_hub, "InferenceClient", _FakeClient)
    return _FakeClient


def _imagine(client, h, img_model=None):
    body = {"message": "a lighthouse at dawn", "mode": "imagine", "promptRefinement": False,
            "conversation_id": f"img-{uuid.uuid4().hex[:6]}"}
    if img_model is not None:
        body["imgModel"] = img_model
    r = client.post("/chat", headers=h, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_web_images_go_to_hugging_face_without_comfyui(client, web, fake_hub):
    # A visitor whose settings still say ComfyUI (or nothing) gets an image, not "set up ComfyUI".
    for img_model in (None, "", "dreamshaper_8.safetensors"):
        data = _imagine(client, _user(client), img_model)
        assert data["media"] and data["media"]["provider"] == "huggingface", data
        assert "not configured" not in data["text"]
    assert ("token", "hf_space_token_123") in fake_hub.calls


def test_an_image_model_that_is_down_falls_through(client, web, fake_hub):
    first = _hf().defaults("image")[0]
    fake_hub.down = {first: 503}
    data = _imagine(client, _user(client))
    models = [m for kind, m in fake_hub.calls if kind == "model"]
    assert models[0] == first and len(set(models)) == 2
    assert data["media"]["model"] == "hf:" + models[-1]


def test_out_of_credits_stops_and_says_so(client, web, fake_hub):
    first = _hf().defaults("image")[0]
    fake_hub.down = {first: 402}
    data = _imagine(client, _user(client))
    assert data["media"] is None and "out of inference credits" in data["text"]
    assert len({m for kind, m in fake_hub.calls if kind == "model"}) == 1


def test_local_images_stay_on_comfyui(local, monkeypatch):
    monkeypatch.setattr(sys.modules["app.config"], "COMFY_BASE_URL", "")
    assert _hf().route_image("dreamshaper_8.safetensors") is None
    assert _hf().route_image(None) is None
    assert _hf().route_image("hf:org/model") == "hf:org/model"   # an explicit Hugging Face pick still works
