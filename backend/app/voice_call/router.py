"""
Public HTTP + WebSocket surface.

All endpoints live under ``/v1/voice-call/*``. The router is built
dynamically so that with ``VOICE_CALL_ENABLED=false`` it returns an
empty router — no endpoints, no 500s, no accidental exposure.

Mount from main.py ONCE, always behind the feature flag::

    from .voice_call.router import build_router, build_ws_router
    from .voice_call.config import load as _vc_load
    _vc_cfg = _vc_load()
    if _vc_cfg.enabled:
        app.include_router(build_router(_vc_cfg))
        app.include_router(build_ws_router(_vc_cfg))
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import (
    APIRouter, Cookie, Depends, Header, HTTPException,
    Query, WebSocket,
)
from fastapi.responses import JSONResponse

from . import service, store, ws as ws_mod
from .config import VoiceCallConfig
from .models import (
    Capabilities, CreateSessionReq, CreateSessionResp,
    EndSessionResp, HintsResp, Session,
)
from .policy import PolicyError


logger = logging.getLogger("voice_call.http")


# ── shared auth resolver (matches main._scoped_user_or_none) ──────────
# Kept inline to avoid a circular import. Same semantics: single-user
# installs auto-resolve to the default user; multi-user installs require
# a bearer token.

def _resolve_user(
    authorization: str,
    homepilot_session: Optional[str],
) -> dict:
    from ..users import (
        ensure_users_tables, _validate_token,
        get_or_create_default_user, count_users,
    )
    ensure_users_tables()
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token and homepilot_session:
        token = homepilot_session.strip()
    user = _validate_token(token) if token else None
    if user:
        return user
    if count_users() > 1:
        raise HTTPException(status_code=401, detail="Authentication required")
    return get_or_create_default_user()


# ── helpers ────────────────────────────────────────────────────────────

def _public_session(row: dict) -> Session:
    """Strip the resume_token out before the dict leaves the server."""
    duration = None
    if row.get("ended_at") and row.get("started_at"):
        duration = int((int(row["ended_at"]) - int(row["started_at"])) / 1000)
    return Session(
        id=row["id"],
        user_id=row["user_id"],
        conversation_id=row.get("conversation_id"),
        persona_id=row.get("persona_id"),
        entry_mode=row["entry_mode"],
        status=row["status"],
        started_at=int(row["started_at"]),
        ended_at=int(row["ended_at"]) if row.get("ended_at") else None,
        ended_reason=row.get("ended_reason"),
        duration_sec=duration,
    )


def _ws_url_for(session_id: str) -> str:
    """The WS URL the client should open. Override via env for
    containerized deployments where 127.0.0.1 is wrong."""
    base = (
        os.getenv("VOICE_CALL_PUBLIC_WS_BASE")
        or "ws://127.0.0.1:8000"
    ).rstrip("/")
    return f"{base}/v1/voice-call/ws/{session_id}"


# ── HTTP router ────────────────────────────────────────────────────────

def build_router(cfg: VoiceCallConfig) -> APIRouter:
    """Return the REST sub-router. Empty router if feature off."""
    r = APIRouter(prefix="/v1/voice-call", tags=["voice-call"])
    if not cfg.enabled:
        return r  # feature off → empty surface

    @r.post("/sessions", response_model=CreateSessionResp, status_code=201)
    def create_session(
        body: CreateSessionReq,
        authorization: str = Header(default=""),
        homepilot_session: Optional[str] = Cookie(default=None),
    ):
        user = _resolve_user(authorization, homepilot_session)
        try:
            row = service.create_session(
                user_id=user["id"],
                conversation_id=body.conversation_id,
                persona_id=body.persona_id,
                entry_mode=body.entry_mode,
                client_platform=body.device_info.platform,
                app_version=body.device_info.app_version,
                cfg=cfg,
            )
        except PolicyError as exc:
            logger.warning(
                "[call] create_session policy_error user=%s code=%s status=%s",
                user["id"], exc.code, exc.http_status,
            )
            return JSONResponse(
                status_code=exc.http_status,
                content={"ok": False, "code": exc.code, "detail": exc.detail},
            )
        logger.info(
            "[call] create_session ok user=%s sid=%s persona=%s conv=%s",
            user["id"], row["id"], body.persona_id, body.conversation_id,
        )
        # Token is only returned in the create response — never again.
        expires_at = int(row["created_at"]) + 15 * 60 * 1000
        return CreateSessionResp(
            session_id=row["id"],
            ws_url=_ws_url_for(row["id"]),
            resume_token=row["resume_token"],
            expires_at=expires_at,
            max_duration_sec=cfg.max_duration_sec,
            capabilities=Capabilities(
                interruptions=False,
                # barge_in reflects the combined streaming + barge-in
                # flag pair — it only works when the session actually
                # streams, since there's nothing to cancel in unary.
                barge_in=cfg.streaming_enabled and cfg.barge_in_enabled,
                # transcript_live = streaming assistant partials.
                transcript_live=cfg.streaming_enabled,
                streaming=cfg.streaming_enabled,
            ),
        )

    @r.get("/sessions/{sid}", response_model=Session)
    def get_session(
        sid: str,
        authorization: str = Header(default=""),
        homepilot_session: Optional[str] = Cookie(default=None),
    ):
        user = _resolve_user(authorization, homepilot_session)
        row = service.get(sid, user["id"])
        if row is None:
            # 404, never 403 — probe-safe.
            logger.info("[call] get_session miss user=%s sid=%s", user["id"], sid)
            raise HTTPException(status_code=404, detail="Session not found")
        return _public_session(row)

    @r.post("/sessions/{sid}/end", response_model=EndSessionResp)
    def end_session_ep(
        sid: str,
        authorization: str = Header(default=""),
        homepilot_session: Optional[str] = Cookie(default=None),
    ):
        user = _resolve_user(authorization, homepilot_session)
        row = service.end_session(sid=sid, user_id=user["id"])
        if row is None:
            logger.info("[call] end_session miss user=%s sid=%s", user["id"], sid)
            raise HTTPException(status_code=404, detail="Session not found")
        logger.info(
            "[call] end_session ok user=%s sid=%s reason=%s",
            user["id"], sid, row.get("ended_reason"),
        )
        public = _public_session(row)
        return EndSessionResp(
            session_id=public.id,
            status=public.status,
            ended_at=public.ended_at or int(row["updated_at"]),
            ended_reason=public.ended_reason or "user_ended",
            duration_sec=public.duration_sec or 0,
        )

    @r.get("/hints", response_model=HintsResp)
    def hints():
        # Public on purpose — the client needs this BEFORE it has a
        # session. Still costs nothing to allow without auth.
        return HintsResp()

    return r


# ── WS router ──────────────────────────────────────────────────────────

def build_ws_router(cfg: VoiceCallConfig) -> APIRouter:
    r = APIRouter(prefix="/v1/voice-call", tags=["voice-call"])
    if not cfg.enabled or not cfg.websocket_enabled:
        return r

    @r.websocket("/ws/{session_id}")
    async def voice_call_ws(
        websocket: WebSocket,
        session_id: str,
        resume_token: Optional[str] = Query(default=None),
    ):
        # Accept first so we can close with a clean error code if needed.
        await websocket.accept()
        await ws_mod.run_session_ws(
            websocket, session_id, resume_token, cfg,
        )

    return r
