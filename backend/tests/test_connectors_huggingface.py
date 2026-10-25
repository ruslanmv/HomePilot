"""
Settings → Connectors: link a Hugging Face account, list its models per type in Models, and
use them for chat, images and video. The token stays on the server; one user's token is never
used for another; nothing changes until a connector is linked.
"""
from __future__ import annotations

import io
import json
import sys
import uuid


def _user(client):
    username = f"c{uuid.uuid4().hex[:10]}"
    r = client.post("/v1/auth/register", json={"username": username})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _hf():
    return sys.modules["app.connectors.huggingface"]


def _fake_whoami(monkeypatch, name="ada"):
    async def whoami(secret):
        if secret != "hf_good_token_123":
            raise ValueError("Hugging Face did not accept this token.")
        return {"name": name, "type": "user"}
    monkeypatch.setattr(_hf(), "whoami", whoami)


def test_catalog_lists_hugging_face_unlinked(client):
    h = _user(client)
    body = client.get("/v1/connectors", headers=h).json()
    hf = next(c for c in body["connectors"] if c["id"] == "huggingface")
    assert hf["connected"] is False and hf["auth"] == "token"


def test_link_keeps_the_token_on_the_server(client, monkeypatch):
    _fake_whoami(monkeypatch)
    h = _user(client)
    r = client.post("/v1/connectors/huggingface", json={"token": "hf_good_token_123"}, headers=h)
    assert r.status_code == 200 and r.json()["account"] == "ada"
    listed = client.get("/v1/connectors", headers=h)
    assert "hf_good_token_123" not in listed.text
    assert next(c for c in listed.json()["connectors"] if c["id"] == "huggingface")["connected"] is True


def test_a_bad_token_is_refused(client, monkeypatch):
    _fake_whoami(monkeypatch)
    h = _user(client)
    r = client.post("/v1/connectors/huggingface", json={"token": "hf_wrong_token_9"}, headers=h)
    assert r.status_code == 400 and "did not accept" in r.json()["detail"]


def test_one_users_token_is_not_anothers(client, monkeypatch):
    _fake_whoami(monkeypatch)
    a, b = _user(client), _user(client)
    client.post("/v1/connectors/huggingface", json={"token": "hf_good_token_123"}, headers=a)
    other = client.get("/v1/connectors", headers=b).json()
    assert next(c for c in other["connectors"] if c["id"] == "huggingface")["connected"] is False


def test_unlink(client, monkeypatch):
    _fake_whoami(monkeypatch)
    h = _user(client)
    client.post("/v1/connectors/huggingface", json={"token": "hf_good_token_123"}, headers=h)
    client.delete("/v1/connectors/huggingface", headers=h)
    body = client.get("/v1/connectors", headers=h).json()
    assert next(c for c in body["connectors"] if c["id"] == "huggingface")["connected"] is False


def test_models_per_type_in_models(client, monkeypatch):
    hf = _hf()
    seen = []

    def fake_list(task, secret):
        seen.append(task)
        return [{"id": f"hf:org/{task}-model" if task in ("image", "video") else f"org/{task}-model",
                 "name": f"org/{task}-model", "likes": 1, "downloads": 2}]
    monkeypatch.setattr(hf, "_list", fake_list)
    monkeypatch.setattr(hf, "_cache", {})
    h = _user(client)
    for model_type, expected in (("chat", "org/chat-model"), ("multimodal", "org/multimodal-model"),
                                 ("image", "hf:org/image-model"), ("video", "hf:org/video-model")):
        body = client.get(f"/models?provider=huggingface&model_type={model_type}", headers=h).json()
        assert body["ok"] is True and body["models"] == [expected], body
    assert seen == ["chat", "multimodal", "image", "video"]
    assert "huggingface" in client.get("/providers").json()["providers"]


def test_chat_goes_through_the_router_with_the_users_token(client, monkeypatch):
    _fake_whoami(monkeypatch)
    h = _user(client)
    client.post("/v1/connectors/huggingface", json={"token": "hf_good_token_123"}, headers=h)
    llm = sys.modules["app.llm"]
    sent = {}

    async def fake_compat(messages, *, temperature, max_tokens, base_url, model, api_key=None):
        sent.update(base_url=base_url, model=model, api_key=api_key)
        return {"choices": [{"message": {"role": "assistant", "content": "hi from the hub"}}]}
    monkeypatch.setattr(llm, "chat_openai_compat", fake_compat)
    r = client.post("/chat", headers=h, json={
        "message": "hello", "mode": "chat", "provider": "huggingface",
        "provider_model": "Qwen/Qwen2.5-72B-Instruct", "conversation_id": f"hf-{uuid.uuid4().hex[:6]}",
    })
    assert r.status_code == 200, r.text
    assert "hi from the hub" in r.json()["text"]
    assert sent == {"base_url": "https://router.huggingface.co/v1",
                    "model": "Qwen/Qwen2.5-72B-Instruct", "api_key": "hf_good_token_123"}
    assert "hf_good_token_123" not in r.text


def test_an_hf_image_model_makes_the_image_on_the_account(client, monkeypatch):
    _fake_whoami(monkeypatch)
    h = _user(client)
    client.post("/v1/connectors/huggingface", json={"token": "hf_good_token_123"}, headers=h)
    from PIL import Image
    calls = {}

    class FakeClient:
        def __init__(self, provider=None, token=None, timeout=None):
            calls["token"] = token

        def text_to_image(self, prompt, *, model=None, **kw):
            calls.update(prompt=prompt, model=model)
            return Image.new("RGB", (64, 48), "purple")
    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "InferenceClient", FakeClient)
    r = client.post("/chat", headers=h, json={
        "message": "a cozy cabin", "mode": "imagine", "imgModel": "hf:black-forest-labs/FLUX.1-schnell",
        "promptRefinement": False, "conversation_id": f"img-{uuid.uuid4().hex[:6]}",
    })
    assert r.status_code == 200, r.text
    media = r.json()["media"]
    assert media["provider"] == "huggingface" and media["model"] == "hf:black-forest-labs/FLUX.1-schnell"
    assert media["images"][0].startswith("/files/")
    assert calls["token"] == "hf_good_token_123" and calls["model"] == "black-forest-labs/FLUX.1-schnell"
    assert client.get(media["images"][0], headers=h).status_code == 200


def test_an_unlinked_account_is_told_how_to_link(client):
    h = _user(client)
    r = client.post("/chat", headers=h, json={
        "message": "a cozy cabin", "mode": "imagine", "imgModel": "hf:black-forest-labs/FLUX.1-schnell",
        "promptRefinement": False, "conversation_id": f"img-{uuid.uuid4().hex[:6]}",
    })
    assert r.status_code == 200 and "Settings → Connectors" in r.json()["text"]
