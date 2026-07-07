"""
OllaBridge GPU-node routing — provider credential pass-through.

Verifies that chat_openai_compat attaches ``Authorization: Bearer <token>``
when the request-scoped PROVIDER_API_KEY contextvar (set by /chat from
ChatIn.provider_api_key) or the explicit ``api_key`` argument is present,
and sends no auth header otherwise (legacy behavior preserved).
"""
import pytest

import app.llm as llm_mod


class _Resp:
    status_code = 200

    @staticmethod
    def json():
        return {"choices": [{"message": {"content": "ok"}}]}

    @staticmethod
    def raise_for_status():
        return None


@pytest.fixture()
def capture_post(monkeypatch):
    calls = {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            calls["url"] = url
            calls["headers"] = headers or {}
            return _Resp()

    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", _Client)
    return calls


@pytest.mark.anyio
async def test_no_key_no_auth_header(capture_post):
    tok = llm_mod.PROVIDER_API_KEY.set("")
    try:
        await llm_mod.chat_openai_compat(
            [{"role": "user", "content": "hi"}], base_url="http://x/v1", model="m"
        )
    finally:
        llm_mod.PROVIDER_API_KEY.reset(tok)
    assert "Authorization" not in capture_post["headers"]


@pytest.mark.anyio
async def test_contextvar_key_sets_bearer(capture_post):
    tok = llm_mod.PROVIDER_API_KEY.set("cloud-jwt-123")
    try:
        await llm_mod.chat_openai_compat(
            [{"role": "user", "content": "hi"}], base_url="http://x/v1", model="m"
        )
    finally:
        llm_mod.PROVIDER_API_KEY.reset(tok)
    assert capture_post["headers"].get("Authorization") == "Bearer cloud-jwt-123"


@pytest.mark.anyio
async def test_explicit_api_key_wins(capture_post):
    tok = llm_mod.PROVIDER_API_KEY.set("ctx-key")
    try:
        await llm_mod.chat_openai_compat(
            [{"role": "user", "content": "hi"}],
            base_url="http://x/v1",
            model="m",
            api_key="explicit-key",
        )
    finally:
        llm_mod.PROVIDER_API_KEY.reset(tok)
    assert capture_post["headers"].get("Authorization") == "Bearer explicit-key"


def test_chatin_accepts_provider_api_key():
    """The /chat request model exposes the additive field."""
    from app.main import ChatIn

    inp = ChatIn(message="hi", provider_api_key="tok123")
    assert inp.provider_api_key == "tok123"
