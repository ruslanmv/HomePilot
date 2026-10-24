"""Hugging Face account chat is a Space-only provider.

Off a Space (no SPACE_ID) the provider is absent and chat stays on the local
model. On a Space, sign-in keeps the access token on the server, a signed-in
chat uses Inference Providers, and a signed-out or failed account request
falls back to the local model with a short note.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "deploy" / "huggingface-space" / "README.md"


def _clear_space(monkeypatch):
    monkeypatch.delenv("SPACE_ID", raising=False)
    monkeypatch.delenv("HF_SPACE_ID", raising=False)


def _front_matter() -> str:
    text = README.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    assert len(parts) >= 3
    return parts[1]


def test_space_metadata_asks_only_for_inference_api():
    meta = _front_matter()
    assert "hf_oauth: true" in meta
    assert "inference-api" in meta
    for extra in ("write-repos", "read-repos", "manage-repos", "read-billing", "email", "write-discussions"):
        assert extra not in meta


def test_provider_hidden_without_space_id(client, monkeypatch):
    _clear_space(monkeypatch)
    data = client.get("/providers").json()
    assert "huggingface" not in data["providers"]
    assert "ollama" in data["providers"]
    assert data["providers"]["ollama"]["label"]


def test_provider_shown_on_space_for_chat_only(client, monkeypatch):
    monkeypatch.setenv("SPACE_ID", "ada/homepilot")
    info = client.get("/providers").json()["providers"]["huggingface"]
    assert info["label"] == "Hugging Face (your account)"
    caps = info["capabilities"]
    assert caps["chat"] is True
    assert caps["images"] is False
    assert caps["video"] is False
    assert caps["multimodal"] is False


def test_model_list_only_on_space(client, monkeypatch):
    _clear_space(monkeypatch)
    missing = client.get("/models?provider=huggingface")
    assert missing.status_code == 400
    monkeypatch.setenv("SPACE_ID", "ada/homepilot")
    listed = client.get("/models?provider=huggingface").json()
    assert listed["ok"] is True
    assert "Qwen/Qwen2.5-72B-Instruct" in listed["models"]


def test_login_absent_off_space(client, monkeypatch):
    _clear_space(monkeypatch)
    response = client.get("/v1/hf/login", follow_redirects=False)
    assert response.status_code == 404


def test_login_waits_for_space_rebuild(client, monkeypatch):
    monkeypatch.setenv("SPACE_ID", "ada/homepilot")
    monkeypatch.delenv("OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("OAUTH_CLIENT_SECRET", raising=False)
    body = client.get("/v1/hf/login", follow_redirects=False).json()
    assert body["oauth_ready"] is False
    assert "local model" in body["message"]


def test_login_redirects_to_huggingface(client, monkeypatch):
    monkeypatch.setenv("SPACE_ID", "ada/homepilot")
    monkeypatch.setenv("SPACE_HOST", "ada-homepilot.hf.space")
    monkeypatch.setenv("OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "client-secret")
    response = client.get("/v1/hf/login", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://huggingface.co/oauth/authorize?")
    assert "inference-api" in location
    assert "write-repos" not in location
    assert "client-secret" not in location
    assert "redirect_uri=https%3A%2F%2Fada-homepilot.hf.space%2Fv1%2Fhf%2Fcallback" in location
    assert "hp_hf_state=" in (response.headers.get("set-cookie") or "")


def test_callback_keeps_the_token_on_the_server(client, monkeypatch):
    monkeypatch.setenv("SPACE_ID", "ada/homepilot")
    monkeypatch.setenv("OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "client-secret")
    from app import hf_account

    async def exchange(*, code, redirect_uri):
        assert code == "auth-code"
        return {"access_token": "SECRET-TOKEN", "refresh_token": "SECRET-REFRESH", "expires_in": 3600}

    async def profile(access_token):
        assert access_token == "SECRET-TOKEN"
        return {"name": "ada"}

    monkeypatch.setattr(hf_account, "exchange_authorization_code", exchange)
    monkeypatch.setattr(hf_account, "fetch_profile", profile)
    state = "state-token"
    response = client.get(
        "/v1/hf/callback",
        params={"code": "auth-code", "state": state},
        cookies={"hp_hf_state": state},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/"
    header = response.headers.get("set-cookie") or ""
    assert "hp_hf_sid=" in header
    assert "SECRET-TOKEN" not in header
    assert "SECRET-REFRESH" not in header

    store = hf_account._read_store()
    matches = [
        sid for sid, row in store.items()
        if row.get("access_token") == "SECRET-TOKEN" and row.get("username") == "ada"
    ]
    assert matches
    account = client.get("/v1/hf/account", cookies={"hp_hf_sid": matches[-1]}).json()
    dumped = json.dumps(account)
    assert account["space"] is True
    assert account["signed_in"] is True
    assert account["username"] == "ada"
    assert "SECRET-TOKEN" not in dumped
    assert "access_token" not in dumped


def _chat(client, **extra):
    payload = {
        "message": "hello",
        "mode": "chat",
        "conversation_id": extra.pop("conversation_id"),
        "fun_mode": False,
    }
    payload.update(extra)
    response = client.post("/chat", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_signed_out_space_uses_local_model_with_a_note(client, mock_outbound, monkeypatch):
    monkeypatch.setenv("SPACE_ID", "ada/homepilot")
    data = _chat(client, conversation_id="hf-signed-out", provider="huggingface")
    assert "mock-ollama" in data["text"]
    assert "local model" in data["inference_note"]
    assert data["media"]["inference_note"] == data["inference_note"]


def test_signed_in_space_uses_inference_providers(client, mock_outbound, monkeypatch):
    monkeypatch.setenv("SPACE_ID", "ada/homepilot")
    from app import hf_account
    sid = hf_account.save_session(access_token="hf-user-token", username="ada")
    response = client.post("/chat", json={
        "message": "hello",
        "mode": "chat",
        "conversation_id": "hf-signed-in",
        "fun_mode": False,
        "provider": "huggingface",
        "provider_model": "Qwen/Qwen2.5-72B-Instruct",
    }, cookies={"hp_hf_sid": sid})
    assert response.status_code == 200, response.text
    data = response.json()
    assert "mock-llm" in data["text"]
    assert "inference_note" not in data
    assert "hf-user-token" not in response.text


def test_ollama_on_a_space_is_unchanged(client, mock_outbound, monkeypatch):
    monkeypatch.setenv("SPACE_ID", "ada/homepilot")
    data = _chat(client, conversation_id="hf-ollama", provider="ollama")
    assert "mock-ollama" in data["text"]
    assert "inference_note" not in data


def test_off_space_huggingface_stays_on_the_local_model(client, mock_outbound, monkeypatch):
    _clear_space(monkeypatch)
    data = _chat(client, conversation_id="hf-desktop", provider="huggingface", provider_model="Qwen/Qwen2.5-72B-Instruct")
    assert "mock-ollama" in data["text"]
    assert "inference_note" not in data


def test_failed_account_request_falls_back(client, mock_outbound, monkeypatch):
    monkeypatch.setenv("SPACE_ID", "ada/homepilot")
    from app import hf_account

    async def boom(*_args, **_kwargs):
        raise hf_account.HfAccountError("inference 402")

    monkeypatch.setattr(hf_account, "inference_chat", boom)
    sid = hf_account.save_session(access_token="hf-user-token", username="ada")
    response = client.post("/chat", json={
        "message": "hello",
        "mode": "chat",
        "conversation_id": "hf-fallback",
        "fun_mode": False,
        "provider": "huggingface",
        "provider_model": "Qwen/Qwen2.5-72B-Instruct",
    }, cookies={"hp_hf_sid": sid})
    assert response.status_code == 200, response.text
    data = response.json()
    assert "mock-ollama" in data["text"]
    assert "could not run that request" in data["inference_note"]
    assert "hf-user-token" not in response.text


def test_account_status_off_space_has_no_session(client, monkeypatch):
    _clear_space(monkeypatch)
    body = client.get("/v1/hf/account").json()
    assert body == {
        "ok": True,
        "space": False,
        "signed_in": False,
        "username": None,
        "oauth_ready": False,
    }
