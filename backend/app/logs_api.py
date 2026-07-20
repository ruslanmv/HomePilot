"""
Container log streaming API — Hugging Face Spaces style (ADDITIVE, READ-ONLY).

Lets an operator query a running HomePilot deployment's logs over SSE without
SSH, mirroring HF Spaces' ``/api/spaces/<owner>/<repo>/logs/{run,build}``:

    # live application ("run") logs
    curl -N -H "Authorization: Bearer $HP_TOKEN" \\
      https://homepilot.ruslanmv.com/api/spaces/ruslanmv/HomePilot/logs/run

    # container boot ("build") logs
    curl -N -H "Authorization: Bearer $HP_TOKEN" \\
      https://homepilot.ruslanmv.com/api/spaces/ruslanmv/HomePilot/logs/build

Design notes
------------
* ADDITIVE ONLY: a new APIRouter mounted with one ``include_router`` line.
  It never writes, deletes, or mutates anything — it only *reads* the
  supervisor log files the container already produces.
* Works on both the **web** (container) and **normal/desktop** deployments:
  the log directory is ``HOMEPILOT_LOG_DIR`` (default ``/var/log/supervisor``),
  so a desktop install can point it at its own log path.
* Auth reuses the shared ``API_KEY`` (Bearer or ``X-API-Key``) OR a logged-in
  HomePilot session (JWT / ``homepilot_session`` cookie) OR a same-machine
  request. It is **fail-closed** for anonymous remote callers — logs are never
  served without proof of access, even when no ``API_KEY`` is configured.
* SSE framing matches HF (``data: {"timestamp": ..., "data": ...}``); pass
  ``?format=raw`` for plain lines. Heartbeats keep the stream alive through
  nginx/Caddy, and ``X-Accel-Buffering: no`` disables proxy buffering.

Query params: ``tail`` (initial lines, default 200), ``follow`` (default true —
``tail -f`` semantics), ``format`` (``json`` | ``raw``), ``token`` (alternative
to the Authorization header, handy for browser EventSource which cannot set
headers).
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import time
from datetime import datetime, timezone
from typing import AsyncIterator, List, Optional

from fastapi import APIRouter, Cookie, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import config as _cfg

router = APIRouter(tags=["logs"])

# Allowlist: stream name -> ordered candidate filenames (first existing wins).
# Fixed names only — no user-supplied paths ⇒ no path traversal.
_STREAMS: dict[str, List[str]] = {
    # Hugging Face–compatible aliases
    "run": ["backend-stderr.log", "backend-stdout.log", "supervisord.log"],
    "build": ["supervisord.log"],
    # Explicit per-service streams (nice for targeted debugging)
    "backend": ["backend-stderr.log"],
    "backend-stdout": ["backend-stdout.log"],
    "nginx": ["nginx-stderr.log", "nginx-stdout.log"],
    "comfyui": ["comfyui-stderr.log", "comfyui-stdout.log"],
    "supervisord": ["supervisord.log"],
}

_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_HEARTBEAT_SECS = 15.0
_POLL_SECS = 1.0
_MAX_TAIL = 5000


def _log_dir() -> str:
    """Resolved at call time so desktop/dev installs can override via env."""
    return os.getenv("HOMEPILOT_LOG_DIR", "/var/log/supervisor").rstrip("/") or "/var/log/supervisor"


def _resolve_log_file(stream: str) -> Optional[str]:
    """Map a stream name to an absolute file path inside the log dir.

    Returns the first existing candidate, else the first candidate path (so a
    follower can wait for a not-yet-created file). Returns ``None`` for an
    unknown stream or if a resolved path would escape the log directory.
    """
    candidates = _STREAMS.get(stream)
    if not candidates:
        return None
    base = os.path.realpath(_log_dir())
    fallback: Optional[str] = None
    for name in candidates:
        p = os.path.realpath(os.path.join(base, name))
        # Defense in depth: never escape the log directory.
        if not (p == base or p.startswith(base + os.sep)):
            continue
        if fallback is None:
            fallback = p
        if os.path.isfile(p):
            return p
    return fallback


def _extract_token(authorization: Optional[str], x_api_key: Optional[str], token_q: Optional[str]) -> Optional[str]:
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
    if token_q and token_q.strip():
        return token_q.strip()
    return None


def _authorize(
    request: Request,
    authorization: Optional[str],
    x_api_key: Optional[str],
    homepilot_session: Optional[str],
    token_q: Optional[str],
) -> None:
    """Fail-closed authorization for log access. Raises 401 if unauthorized."""
    supplied = _extract_token(authorization, x_api_key, token_q)

    # 1. Shared API key (constant-time compare).
    api_key = _cfg.API_KEY
    if api_key and supplied and hmac.compare_digest(supplied, api_key):
        return

    # 2. Logged-in HomePilot user session (JWT bearer / query / cookie).
    try:
        from .users import _validate_token, ensure_users_tables

        ensure_users_tables()
        tok = supplied or (homepilot_session.strip() if homepilot_session else "")
        if tok and _validate_token(tok):
            return
    except Exception:
        pass

    # 3. Same-machine request (curl on the box itself is trusted dev traffic).
    try:
        if request.client and request.client.host in _LOCAL_HOSTS:
            return
    except Exception:
        pass

    raise HTTPException(status_code=401, detail="Unauthorized: valid API key or session required")


def _redact(line: str) -> str:
    """Never echo the configured API key back in a log line."""
    key = _cfg.API_KEY
    if key and len(key) >= 8 and key in line:
        line = line.replace(key, "***REDACTED***")
    return line


def _read_tail(path: str, n: int) -> List[str]:
    """Return the last ``n`` lines. Supervisor caps files at a few MB, so
    reading the whole file is cheap and avoids fragile seek arithmetic."""
    if n <= 0 or not os.path.isfile(path):
        return []
    try:
        with open(path, "r", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []
    return [ln.rstrip("\n") for ln in lines[-n:]]


def _sse(payload: str) -> str:
    return f"data: {payload}\n\n"


async def _event_stream(
    path: str,
    tail_n: int,
    follow: bool,
    fmt: str,
    request: Request,
) -> AsyncIterator[str]:
    def render(line: str) -> str:
        line = _redact(line)
        if fmt == "raw":
            return _sse(line)
        return _sse(json.dumps(
            {"timestamp": datetime.now(timezone.utc).isoformat(), "data": line},
            ensure_ascii=False,
        ))

    # Opening comment — helps clients confirm the stream is live.
    yield f": streaming {os.path.basename(path)} (follow={str(follow).lower()})\n\n"

    if not os.path.isfile(path):
        yield render(f"[logs] {os.path.basename(path)} not present yet at {_log_dir()} — waiting…")

    # Initial tail.
    for line in _read_tail(path, tail_n):
        yield render(line)

    if not follow:
        return

    # Follow loop (tail -f semantics), robust to rotation/truncation.
    try:
        offset = os.path.getsize(path) if os.path.isfile(path) else 0
    except OSError:
        offset = 0
    buf = ""
    last_emit = time.monotonic()

    while True:
        if await request.is_disconnected():
            break
        try:
            if os.path.isfile(path):
                size = os.path.getsize(path)
                if size < offset:          # rotated / truncated
                    offset, buf = 0, ""
                if size > offset:
                    with open(path, "r", errors="replace") as f:
                        f.seek(offset)
                        chunk = f.read()
                        offset = f.tell()
                    buf += chunk
                    *complete, buf = buf.split("\n")
                    for line in complete:
                        yield render(line)
                        last_emit = time.monotonic()
        except Exception:
            # Never let a transient read error kill the stream.
            pass

        if time.monotonic() - last_emit >= _HEARTBEAT_SECS:
            yield ": keep-alive\n\n"
            last_emit = time.monotonic()

        await asyncio.sleep(_POLL_SECS)


@router.get("/api/spaces/{owner}/{repo}/logs")
async def list_space_logs(
    owner: str,
    repo: str,
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    homepilot_session: Optional[str] = Cookie(default=None),
    token: Optional[str] = Query(default=None),
) -> JSONResponse:
    """Discovery endpoint: which log streams exist and how big they are."""
    _authorize(request, authorization, x_api_key, homepilot_session, token)
    streams = {}
    for name in _STREAMS:
        f = _resolve_log_file(name)
        exists = bool(f and os.path.isfile(f))
        streams[name] = {
            "available": exists,
            "path": f,
            "size_bytes": (os.path.getsize(f) if exists else 0),
        }
    return JSONResponse({
        "ok": True,
        "space": f"{owner}/{repo}",
        "log_dir": _log_dir(),
        "streams": streams,
    })


@router.get("/api/spaces/{owner}/{repo}/logs/{stream}")
async def stream_space_logs(
    owner: str,
    repo: str,
    stream: str,
    request: Request,
    tail: int = Query(default=200, ge=0, le=_MAX_TAIL),
    follow: bool = Query(default=True),
    fmt: str = Query(default="json", alias="format"),
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    homepilot_session: Optional[str] = Cookie(default=None),
    token: Optional[str] = Query(default=None),
) -> StreamingResponse:
    """Stream a log ``stream`` over SSE (``run``, ``build``, or a service name)."""
    _authorize(request, authorization, x_api_key, homepilot_session, token)

    if stream not in _STREAMS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown log stream '{stream}'. Available: {', '.join(sorted(_STREAMS))}",
        )
    path = _resolve_log_file(stream)
    if not path:
        raise HTTPException(status_code=404, detail="Log stream path could not be resolved")

    normalized = "raw" if str(fmt).lower() == "raw" else "json"
    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",   # nginx: don't buffer the SSE stream
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        _event_stream(path, tail, follow, normalized, request),
        media_type="text/event-stream",
        headers=headers,
    )
