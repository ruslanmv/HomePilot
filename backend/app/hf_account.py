"""Hugging Face account chat — Space only.

A Space sets ``SPACE_ID``. On that host, Models → Chat and Settings → Chat
provider can offer **Hugging Face (your account)**. Sign-in is the Space OAuth
flow (``inference-api`` only). The access token stays in a server-side session;
the browser only holds an opaque cookie.

Chat goes through Inference Providers and is billed to the signed-in account
(free monthly credits or Pro). Signed out, or the account cannot run the
request, the reply comes from the local model already running in the session.

On a computer ``SPACE_ID`` is absent, so this provider is not advertised and
the local Ollama path is unchanged.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import threading
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Request
from fastapi.responses import JSONResponse, RedirectResponse

router = APIRouter(tags=["hf-account"])

SESSION_COOKIE = "hp_hf_sid"
STATE_COOKIE = "hp_hf_state"
ROUTER_URL = "https://router.huggingface.co/v1/chat/completions"

# A larger model than the Space's local default. Overridable, never required.
DEFAULT_MODEL = os.getenv("HF_INFERENCE_MODEL", "Qwen/Qwen2.5-72B-Instruct").strip() or "Qwen/Qwen2.5-72B-Instruct"

# Curated chat models that Inference Providers can run on the signed-in account.
CHAT_MODELS: List[str] = [
    "Qwen/Qwen2.5-72B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct",
    "meta-llama/Llama-3.3-70B-Instruct",
    "meta-llama/Llama-3.1-8B-Instruct",
    "mistralai/Mistral-Small-24B-Instruct-2501",
    "google/gemma-2-27b-it",
]

NOTE_SIGNED_OUT = "Signed out of Hugging Face, so this reply used the local model."
NOTE_UNAVAILABLE = "Your Hugging Face account could not run that request, so this reply used the local model."
SIGNIN_LATER = "Sign-in starts after this Space rebuilds. Until then, chat uses the local model."

# Request-scoped. The middleware sets these from the opaque cookie. Empty means
# signed out. The token itself is never written into a response.
HF_USER_TOKEN: ContextVar[str] = ContextVar("hp_hf_user_token", default="")
HF_SESSION_ID: ContextVar[str] = ContextVar("hp_hf_session_id", default="")

_lock = threading.Lock()


class HfAccountError(Exception):
    """The signed-in account could not run this inference request."""


def is_hf_space() -> bool:
    """True only when this process is the Hugging Face web edition."""
    return bool(os.getenv("SPACE_ID", "").strip() or os.getenv("HF_SPACE_ID", "").strip())


def _session_path() -> Path:
    override = os.getenv("HF_SESSION_PATH", "").strip()
    if override:
        return Path(override)
    from .config import SQLITE_PATH
    return Path(SQLITE_PATH).parent / "hf_sessions.json"


def _read_store() -> Dict[str, Any]:
    path = _session_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_store(data: Dict[str, Any]) -> None:
    path = _session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _session(sid: str) -> Optional[Dict[str, Any]]:
    if not sid:
        return None
    with _lock:
        row = _read_store().get(sid)
    return row if isinstance(row, dict) else None


def save_session(
    *,
    access_token: str,
    username: str = "",
    refresh_token: str = "",
    expires_in: Optional[int] = None,
    sid: Optional[str] = None,
) -> str:
    """Persist a token server-side. Returns the opaque session id."""
    token = (access_token or "").strip()
    if not token:
        raise ValueError("missing access token")
    session_id = (sid or "").strip() or secrets.token_urlsafe(24)
    try:
        ttl = int(expires_in) if expires_in else 8 * 3600
    except (TypeError, ValueError):
        ttl = 8 * 3600
    row = {
        "access_token": token,
        "refresh_token": (refresh_token or "").strip(),
        "username": (username or "").strip(),
        "expires_at": time.time() + max(60, ttl),
    }
    with _lock:
        store = _read_store()
        store[session_id] = row
        _write_store(store)
    return session_id


def drop_session(sid: str) -> None:
    if not sid:
        return
    with _lock:
        store = _read_store()
        if sid in store:
            store.pop(sid, None)
            _write_store(store)


def public_session(sid: Optional[str]) -> Dict[str, Any]:
    """What the browser may see. Never includes the access token."""
    row = _session(sid or "")
    if not row or not str(row.get("access_token") or "").strip():
        return {"signed_in": False, "username": None}
    name = str(row.get("username") or "").strip() or None
    return {"signed_in": True, "username": name}


def token_for_sid(sid: Optional[str]) -> str:
    row = _session(sid or "")
    if not row:
        return ""
    return str(row.get("access_token") or "").strip()


def bind_session_cookie(sid: Optional[str]):
    """Bind this request's server-side token. Returns reset handles."""
    sid_token = HF_SESSION_ID.set((sid or "").strip())
    user_token = HF_USER_TOKEN.set(token_for_sid(sid))
    return sid_token, user_token


def oauth_config() -> Optional[Dict[str, str]]:
    client_id = os.getenv("OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "provider": os.getenv("OPENID_PROVIDER_URL", "https://huggingface.co").rstrip("/"),
        "host": os.getenv("SPACE_HOST", "").strip(),
    }


def oauth_ready() -> bool:
    return oauth_config() is not None


def redirect_uri(request: Request) -> str:
    cfg = oauth_config()
    host = (cfg or {}).get("host") or os.getenv("SPACE_HOST", "").strip()
    if host:
        return f"https://{host}/v1/hf/callback"
    return f"{str(request.base_url).rstrip('/')}/v1/hf/callback"


def _same_secret(left: str, right: str) -> bool:
    try:
        return secrets.compare_digest(left, right)
    except Exception:
        return False


def _cookie_secure(request: Request) -> bool:
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "")
    return proto.split(",")[0].strip().lower() == "https"


def _basic_auth(cfg: Dict[str, str]) -> str:
    raw = f"{cfg['client_id']}:{cfg['client_secret']}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


def authorize_url(*, redirect_uri: str, state: str) -> str:
    cfg = oauth_config()
    if not cfg:
        raise HfAccountError("oauth not ready")
    # openid + profile are always granted on a Space. The only extra permission
    # this Space asks for is inference-api.
    query = urlencode({
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "scope": "openid profile inference-api",
        "state": state,
    })
    return f"{cfg['provider']}/oauth/authorize?{query}"


def chat_model_ids() -> List[str]:
    models = list(CHAT_MODELS)
    if DEFAULT_MODEL and DEFAULT_MODEL not in models:
        models.insert(0, DEFAULT_MODEL)
    return models


def account_status(sid: Optional[str]) -> Dict[str, Any]:
    space = is_hf_space()
    body: Dict[str, Any] = {
        "ok": True,
        "space": space,
        "signed_in": False,
        "username": None,
        "oauth_ready": bool(space and oauth_ready()),
    }
    if not space:
        return body
    pub = public_session(sid)
    body["signed_in"] = pub["signed_in"]
    body["username"] = pub["username"]
    body["default_model"] = DEFAULT_MODEL
    body["models"] = chat_model_ids()
    return body


async def exchange_authorization_code(*, code: str, redirect_uri: str) -> Dict[str, Any]:
    cfg = oauth_config()
    if not cfg:
        raise HfAccountError("oauth not ready")
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"{cfg['provider']}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": cfg["client_id"],
            },
            headers={"Authorization": _basic_auth(cfg)},
        )
    if response.status_code >= 400:
        raise HfAccountError(f"token exchange failed ({response.status_code})")
    data = response.json()
    if not isinstance(data, dict) or not str(data.get("access_token") or "").strip():
        raise HfAccountError("token exchange returned no access token")
    return data


async def fetch_profile(access_token: str) -> Dict[str, Any]:
    cfg = oauth_config() or {"provider": "https://huggingface.co"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{cfg['provider']}/api/whoami-v2",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if response.status_code >= 400:
            return {}
        data = response.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def refresh_session(sid: str) -> str:
    row = _session(sid)
    cfg = oauth_config()
    refresh = str((row or {}).get("refresh_token") or "").strip()
    if not row or not refresh or not cfg:
        return ""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{cfg['provider']}/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh,
                    "client_id": cfg["client_id"],
                },
                headers={"Authorization": _basic_auth(cfg)},
            )
        if response.status_code >= 400:
            return ""
        data = response.json()
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    access = str(data.get("access_token") or "").strip()
    if not access:
        return ""
    save_session(
        sid=sid,
        access_token=access,
        refresh_token=str(data.get("refresh_token") or refresh),
        username=str(row.get("username") or ""),
        expires_in=data.get("expires_in"),
    )
    return access


def _message_text(data: Dict[str, Any]) -> str:
    try:
        return str(data["choices"][0]["message"]["content"] or "")
    except Exception:
        return ""


async def _post_inference(
    *,
    token: str,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float,
    max_tokens: int,
) -> Dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": m.get("role") or "user", "content": m.get("content") if isinstance(m.get("content"), str) else str(m.get("content") or "")}
            for m in messages
            if isinstance(m, dict)
        ],
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(
            ROUTER_URL,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
    if response.status_code >= 400:
        # Status only. The body can echo request details; the token must not
        # land in a log line or a user-facing error.
        raise HfAccountError(f"inference {response.status_code}")
    try:
        data = response.json()
    except Exception as exc:
        raise HfAccountError("inference returned an unreadable reply") from exc
    if not isinstance(data, dict) or not _message_text(data).strip():
        raise HfAccountError("inference returned an empty reply")
    return data


async def inference_chat(
    messages: List[Dict[str, Any]],
    *,
    model: str,
    temperature: float,
    max_tokens: int,
) -> Dict[str, Any]:
    token = HF_USER_TOKEN.get().strip()
    if not token:
        raise HfAccountError("signed out")
    sid = HF_SESSION_ID.get().strip()
    row = _session(sid) if sid else None
    if row and float(row.get("expires_at") or 0) <= time.time():
        refreshed = await refresh_session(sid)
        if refreshed:
            token = refreshed
    try:
        return await _post_inference(
            token=token, model=model, messages=messages,
            temperature=temperature, max_tokens=max_tokens,
        )
    except HfAccountError as exc:
        if sid and "401" in str(exc):
            refreshed = await refresh_session(sid)
            if refreshed:
                return await _post_inference(
                    token=refreshed, model=model, messages=messages,
                    temperature=temperature, max_tokens=max_tokens,
                )
        raise


async def chat_via_account(
    messages: List[Dict[str, Any]],
    *,
    temperature: float,
    max_tokens: int,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Run Inference Providers, or the local model with a short note.

    Off a Space this is the local model with no note, so a desktop install
    that never shows this provider stays on Ollama.
    """
    from .llm import chat_ollama

    hf_model = (model or "").strip() or DEFAULT_MODEL
    note = ""
    if is_hf_space():
        if not HF_USER_TOKEN.get().strip():
            note = NOTE_SIGNED_OUT
        else:
            try:
                return await inference_chat(
                    messages,
                    model=hf_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception:
                note = NOTE_UNAVAILABLE

    # Never hand an Inference Providers id (``org/name``) to the local runtime.
    result = await chat_ollama(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        model=None,
    )
    if note:
        result = dict(result)
        result["hf_note"] = note
    return result


def _set_cookie(response, request: Request, key: str, value: str, max_age: int) -> None:
    response.set_cookie(
        key=key,
        value=value,
        max_age=max_age,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        path="/",
    )


@router.get("/v1/hf/account")
async def hf_account(hp_hf_sid: Optional[str] = Cookie(default=None)) -> JSONResponse:
    body = account_status(hp_hf_sid)
    return JSONResponse(status_code=200, content=body, headers={"Cache-Control": "no-store"})


@router.get("/v1/hf/login")
async def hf_login(request: Request) -> JSONResponse:
    if not is_hf_space():
        return JSONResponse(status_code=404, content={"ok": False, "space": False})
    if not oauth_ready():
        return JSONResponse(status_code=200, content={
            "ok": False,
            "oauth_ready": False,
            "message": SIGNIN_LATER,
        })
    state = secrets.token_urlsafe(24)
    target = authorize_url(redirect_uri=redirect_uri(request), state=state)
    response = RedirectResponse(target, status_code=302)
    _set_cookie(response, request, STATE_COOKIE, state, max_age=600)
    return response  # type: ignore[return-value]


@router.get("/v1/hf/callback")
async def hf_callback(
    request: Request,
    code: str = "",
    state: str = "",
    hp_hf_state: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    if not is_hf_space():
        return JSONResponse(status_code=404, content={"ok": False, "space": False})
    if not code or not state or not hp_hf_state or not _same_secret(state, hp_hf_state):
        return RedirectResponse("/?hf_signin=failed", status_code=302)  # type: ignore[return-value]
    try:
        granted = await exchange_authorization_code(code=code, redirect_uri=redirect_uri(request))
    except Exception:
        return RedirectResponse("/?hf_signin=failed", status_code=302)  # type: ignore[return-value]
    access = str(granted.get("access_token") or "").strip()
    profile = await fetch_profile(access)
    username = str(profile.get("name") or profile.get("fullname") or "").strip()
    sid = save_session(
        access_token=access,
        username=username,
        refresh_token=str(granted.get("refresh_token") or ""),
        expires_in=granted.get("expires_in"),
    )
    response = RedirectResponse("/", status_code=302)
    _set_cookie(response, request, SESSION_COOKIE, sid, max_age=30 * 24 * 3600)
    response.delete_cookie(STATE_COOKIE, path="/")
    return response  # type: ignore[return-value]


@router.post("/v1/hf/logout")
async def hf_logout(hp_hf_sid: Optional[str] = Cookie(default=None)) -> JSONResponse:
    drop_session(hp_hf_sid or "")
    response = JSONResponse(status_code=200, content={"ok": True, "signed_in": False})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
