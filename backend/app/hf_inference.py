"""Hugging Face account inference for the Space web edition.

Anonymous visitors keep the local Ollama model. A visitor who signs in with
Hugging Face grants the ``inference-api`` scope, and chat then calls
Inference Providers with that user's token so the call spends their credits
(free monthly credits or a Pro plan). The token stays in this process.
The browser only holds an HttpOnly session id.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import os
import secrets
import time
from contextvars import ContextVar
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import httpx

ROUTER_BASE = "https://router.huggingface.co/v1"
SESSION_COOKIE = "hp_hf_session"
# Documented Space callback. Any URI is accepted as long as it targets the Space
# and the authorize request sends the same value.
CALLBACK_PATH = "/login/callback"
SESSION_TTL_S = 8 * 3600
STATE_TTL_S = 10 * 60

# A short chat list. The signed-in model list replaces it when the router answers.
CURATED_MODELS = [
    "Qwen/Qwen2.5-7B-Instruct",
    "meta-llama/Llama-3.1-8B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "HuggingFaceTB/SmolLM2-1.7B-Instruct",
]

NOTICE_SIGNED_OUT = (
    "Using the local model for this reply. Sign in with Hugging Face to use your account credits."
)
NOTICE_FALLBACK = (
    "Using the local model for this reply. Hugging Face could not run this request on your account."
)

_TOKEN: ContextVar[str] = ContextVar("hf_access_token", default="")
_SID: ContextVar[str] = ContextVar("hf_session_id", default="")

# Process-local. A Space restart signs everyone out, which matches "this session".
_SESSIONS: Dict[str, Dict[str, Any]] = {}
_SECRET = secrets.token_bytes(32)


def on_huggingface() -> bool:
    """True when this process is a Hugging Face Space, not a local install."""
    return bool(os.getenv("SPACE_ID") or os.getenv("HF_SPACE_ID") or os.getenv("SPACE_HOST"))


def oauth_configured() -> bool:
    return bool(os.getenv("OAUTH_CLIENT_ID", "").strip() and os.getenv("OAUTH_CLIENT_SECRET", "").strip())


def _provider_url() -> str:
    return (os.getenv("OPENID_PROVIDER_URL") or "https://huggingface.co").rstrip("/")


def _scopes() -> str:
    raw = (os.getenv("OAUTH_SCOPES") or "openid profile inference-api").strip()
    if "inference-api" not in raw.split():
        raw = f"{raw} inference-api"
    return raw


def redirect_uri(request_base: str = "") -> str:
    host = (os.getenv("SPACE_HOST") or "").strip()
    if host:
        return f"https://{host}{CALLBACK_PATH}"
    return f"{(request_base or '').rstrip('/')}{CALLBACK_PATH}"


def sign_state() -> str:
    nonce = secrets.token_urlsafe(16)
    payload = f"{nonce}.{int(time.time())}"
    sig = hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def state_ok(state: str) -> bool:
    if not state or state.count(".") != 2:
        return False
    nonce, ts, sig = state.split(".", 2)
    payload = f"{nonce}.{ts}"
    expected = hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return False
    try:
        issued = int(ts)
    except ValueError:
        return False
    return 0 <= int(time.time()) - issued <= STATE_TTL_S


def authorization_url(redirect: str) -> str:
    query = urlencode({
        "client_id": os.getenv("OAUTH_CLIENT_ID", "").strip(),
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": _scopes(),
        "state": sign_state(),
    })
    return f"{_provider_url()}/oauth/authorize?{query}"


def _purge() -> None:
    now = time.time()
    dead = [sid for sid, row in _SESSIONS.items() if float(row.get("expires_at") or 0) <= now]
    for sid in dead:
        _SESSIONS.pop(sid, None)


def put_session(*, access_token: str, username: str, name: str, expires_in: int) -> str:
    _purge()
    sid = secrets.token_urlsafe(32)
    ttl = min(max(int(expires_in or SESSION_TTL_S), 60), SESSION_TTL_S)
    _SESSIONS[sid] = {
        "access_token": access_token,
        "username": username,
        "name": name or username,
        "expires_at": time.time() + ttl,
    }
    return sid


def drop_session(sid: Optional[str]) -> None:
    if sid:
        _SESSIONS.pop(sid, None)


def session_public(sid: Optional[str]) -> Dict[str, Any]:
    """Status safe to send to the browser. Never includes the access token."""
    _purge()
    row = _SESSIONS.get(sid or "")
    signed_in = bool(row and row.get("access_token"))
    return {
        "on_huggingface": on_huggingface(),
        "oauth_configured": oauth_configured(),
        "signed_in": signed_in,
        "username": row.get("username") if signed_in else None,
        "name": row.get("name") if signed_in else None,
        "default_provider": "ollama",
        "credits": "account",
    }


def bind_hf_session(sid: Optional[str]) -> None:
    """Attach this request's Hugging Face token, if the session is still live."""
    _purge()
    row = _SESSIONS.get(sid or "")
    token = str(row.get("access_token") or "") if row else ""
    _SID.set(sid or "")
    _TOKEN.set(token)


def current_token() -> str:
    return _TOKEN.get()


async def exchange_code(code: str, redirect: str) -> Dict[str, Any]:
    """Trade an authorization code for a session id. Raises RuntimeError on failure."""
    client_id = os.getenv("OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("Hugging Face sign-in is not enabled on this Space.")
    token_url = f"{_provider_url()}/oauth/token"
    async with httpx.AsyncClient(timeout=20.0) as client:
        tok = await client.post(
            token_url,
            data={
                "client_id": client_id,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
            },
            auth=(client_id, client_secret),
        )
        if tok.status_code >= 400:
            raise RuntimeError(f"Hugging Face token exchange failed (HTTP {tok.status_code}).")
        body = tok.json()
        access = str(body.get("access_token") or "")
        if not access:
            raise RuntimeError("Hugging Face did not return an access token.")
        info = await client.get(
            f"{_provider_url()}/oauth/userinfo",
            headers={"Authorization": f"Bearer {access}"},
        )
    username = ""
    name = ""
    if info.status_code < 400:
        profile = info.json()
        if isinstance(profile, dict):
            username = str(profile.get("preferred_username") or profile.get("name") or "")
            name = str(profile.get("name") or username)
    sid = put_session(
        access_token=access,
        username=username,
        name=name,
        expires_in=int(body.get("expires_in") or SESSION_TTL_S),
    )
    return {"sid": sid, "username": username, "name": name or username}


def callback_page(username: str) -> str:
    who = html.escape(username or "your Hugging Face account")
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Signed in — HomePilot</title>
<body style="font-family:system-ui,sans-serif;background:#0b0b10;color:#eee;padding:48px">
<h1>Signed in as {who}</h1>
<p>Chat can now use your Hugging Face credits. You can close this tab and return to HomePilot.</p>
<p>If you sign out, or a request cannot be billed, HomePilot uses the local model in this Space.</p>
</body>"""


def _model_ok(model: Optional[str]) -> str:
    text = (model or "").strip()
    if text.count("/") == 1 and " " not in text and len(text) <= 160:
        return text
    return CURATED_MODELS[0]


async def list_account_models(sid: Optional[str]) -> Tuple[List[str], bool]:
    """(models, live). Live is true when the router answered for this session."""
    row = _SESSIONS.get(sid or "")
    token = str(row.get("access_token") or "") if row else ""
    if not token:
        return list(CURATED_MODELS), False
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{ROUTER_BASE}/models", headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            data = r.json()
        rows = data.get("data") if isinstance(data, dict) else None
        names = sorted({
            str(item.get("id"))
            for item in (rows or [])
            if isinstance(item, dict) and item.get("id") and "/" in str(item.get("id"))
        })
        if names:
            return names[:80], True
    except Exception:
        pass
    return list(CURATED_MODELS), False


async def chat_huggingface(
    messages: List[Dict[str, Any]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 800,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """One chat completion on the signed-in account, else the local model.

    A missing session, a quota error, or an auth error does not fail the turn.
    """
    from .llm import chat_ollama, chat_openai_compat

    chosen = _model_ok(model)
    token = current_token()
    if not token:
        out = await chat_ollama(messages, temperature=temperature, max_tokens=max_tokens)
        out["hf_notice"] = NOTICE_SIGNED_OUT
        return out
    try:
        out = await chat_openai_compat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            base_url=ROUTER_BASE,
            model=chosen,
            api_key=token,
        )
        if isinstance(out, dict):
            out["model"] = chosen
        return out
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        if status in (401, 402, 403, 429) or status >= 500:
            if status in (401, 403):
                drop_session(_SID.get())
            out = await chat_ollama(messages, temperature=temperature, max_tokens=max_tokens)
            out["hf_notice"] = NOTICE_FALLBACK
            return out
        raise
    except httpx.HTTPError:
        out = await chat_ollama(messages, temperature=temperature, max_tokens=max_tokens)
        out["hf_notice"] = NOTICE_FALLBACK
        return out
