"""Hugging Face account inference: detect a Space, keep the token off the browser,
and fall back to the local model when the visitor is signed out."""
import os

import pytest

from app import hf_inference as hf
from app.providers import provider_info


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    hf._SESSIONS.clear()
    hf.bind_hf_session(None)
    for key in ("SPACE_ID", "HF_SPACE_ID", "SPACE_HOST", "OAUTH_CLIENT_ID", "OAUTH_CLIENT_SECRET", "OAUTH_SCOPES"):
        monkeypatch.delenv(key, raising=False)
    yield
    hf._SESSIONS.clear()
    hf.bind_hf_session(None)


def test_a_space_is_detected_and_a_local_install_is_not(monkeypatch):
    assert hf.on_huggingface() is False
    monkeypatch.setenv("SPACE_ID", "ruslanmv/HomePilot")
    assert hf.on_huggingface() is True
    info = provider_info()
    assert "huggingface" in info
    assert info["huggingface"]["account_login"] is True
    assert info["huggingface"]["capabilities"]["images"] is False


def test_local_install_does_not_advertise_the_account_provider():
    assert "huggingface" not in provider_info()


def test_session_status_never_includes_the_access_token():
    sid = hf.put_session(access_token="hf_secret_token", username="ada", name="Ada", expires_in=600)
    public = hf.session_public(sid)
    assert public["signed_in"] is True
    assert public["username"] == "ada"
    assert "hf_secret_token" not in str(public)
    assert "access_token" not in public


def test_authorize_url_requests_inference_on_behalf_of_the_user(monkeypatch):
    monkeypatch.setenv("OAUTH_CLIENT_ID", "client")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("SPACE_HOST", "ruslanmv-homepilot.hf.space")
    url = hf.authorization_url(hf.redirect_uri())
    assert "client_id=client" in url
    assert "inference-api" in url
    assert "redirect_uri=https%3A%2F%2Fruslanmv-homepilot.hf.space%2Flogin%2Fcallback" in url
    state = url.split("state=", 1)[1]
    assert hf.state_ok(state)


def test_a_bad_oauth_state_is_rejected():
    assert hf.state_ok("nope") is False
    assert hf.state_ok(hf.sign_state() + "x") is False


@pytest.mark.asyncio
async def test_signed_out_chat_uses_the_local_model(monkeypatch):
    async def local(messages, **kw):
        return {"choices": [{"message": {"content": "local hello"}}]}

    monkeypatch.setattr("app.llm.chat_ollama", local)
    hf.bind_hf_session(None)
    out = await hf.chat_huggingface([{"role": "user", "content": "hello"}], model="Qwen/Qwen2.5-7B-Instruct")
    assert out["choices"][0]["message"]["content"] == "local hello"
    assert "local model" in out["hf_notice"]


@pytest.mark.asyncio
async def test_a_billing_failure_falls_back_once_and_keeps_the_token_out_of_the_notice(monkeypatch):
    import httpx

    sid = hf.put_session(access_token="hf_secret_token", username="ada", name="Ada", expires_in=600)
    hf.bind_hf_session(sid)

    async def boom(*a, **k):
        req = httpx.Request("POST", "https://router.huggingface.co/v1/chat/completions")
        resp = httpx.Response(402, request=req)
        raise httpx.HTTPStatusError("no credits", request=req, response=resp)

    async def local(messages, **kw):
        return {"choices": [{"message": {"content": "local hello"}}]}

    monkeypatch.setattr("app.llm.chat_openai_compat", boom)
    monkeypatch.setattr("app.llm.chat_ollama", local)
    out = await hf.chat_huggingface([{"role": "user", "content": "hello"}], model="Qwen/Qwen2.5-7B-Instruct")
    assert out["choices"][0]["message"]["content"] == "local hello"
    assert "hf_secret_token" not in out["hf_notice"]
