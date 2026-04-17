"""
Public HTTP surface for persona_call.

Five endpoints, all minor — this module is primarily called from
``voice_call/ws.py`` at runtime. These REST routes are for
observability + admin tuning + client facets lookup.

Mount point in main.py is ONE feature-flagged try/except block.
With ``PERSONA_CALL_ENABLED=false`` :func:`build_router` returns
an empty router — every path 404s, zero schema is created.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter, Cookie, Depends, Header, HTTPException, Query,
)
from pydantic import BaseModel

from . import facets as facets_mod
from . import store
from .config import PersonaCallConfig


# ── auth passthrough (matches main._scoped_user_or_none) ─────────────

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


# ── response models ──────────────────────────────────────────────────

class FacetsResp(BaseModel):
    persona_id: Optional[str]
    warmth: float
    pace: float
    formality: float
    humor: float
    self_disclosure: float
    sentence_max_words: int
    typical_reply_sentences: List[int]
    language_register: str
    signature_tokens: Dict[str, List[str]]
    backchannel_rate: float


class StateResp(BaseModel):
    session_id: str
    phase: str
    turn_index: int
    skipped_how_are_you: bool
    asked_reason_fallback: bool
    reason_for_call: str
    pre_closing_trigger: Optional[str]
    recent_acks: List[str]
    recent_openers: List[str]
    recent_closings: List[str]
    caller_context: Dict[str, Any]


class DirectiveResp(BaseModel):
    session_id: str
    turn_index: int
    phase: str
    applied: bool
    system_suffix: str
    post_directives: List[str]


# ── router builder ───────────────────────────────────────────────────

def build_router(cfg: PersonaCallConfig) -> APIRouter:
    """Construct the FastAPI router. Empty if ``cfg.enabled`` is
    False so main.py's mount is always a safe no-op."""
    r = APIRouter(prefix="/v1/persona-call", tags=["persona-call"])
    if not cfg.enabled:
        return r

    @r.get("/facets/{persona_id}", response_model=FacetsResp)
    def get_facets(persona_id: str):
        f = facets_mod.for_persona_id(persona_id)
        return FacetsResp(
            persona_id=persona_id,
            warmth=f.warmth,
            pace=f.pace,
            formality=f.formality,
            humor=f.humor,
            self_disclosure=f.self_disclosure,
            sentence_max_words=f.sentence_max_words,
            typical_reply_sentences=f.typical_reply_sentences,
            language_register=f.language_register,
            signature_tokens={
                "acknowledgments": list(f.ack_tokens),
                "thinking": list(f.thinking_tokens),
                "pre_closing": list(f.pre_closing_tokens),
                "closings": list(f.closing_tokens),
            },
            backchannel_rate=f.backchannel_rate,
        )

    @r.get("/state/{session_id}", response_model=StateResp)
    def get_state(
        session_id: str,
        authorization: str = Header(default=""),
        homepilot_session: Optional[str] = Cookie(default=None),
    ):
        """Runtime state for the session. Owner-bound via the
        underlying voice_call_sessions row — if the session doesn't
        belong to the caller, return 404 (probe-safe)."""
        user = _resolve_user(authorization, homepilot_session)
        # Ownership is enforced by looking up the voice_call_sessions
        # row first. If that is missing or foreign, we 404 before
        # touching persona_call_state at all.
        try:
            from ..voice_call.store import get_session_for_owner
            vc_row = get_session_for_owner(session_id, user["id"])
        except Exception:
            vc_row = None
        if vc_row is None:
            raise HTTPException(status_code=404, detail="Session not found")
        s = store.get_state(session_id)
        if s is None:
            # Session exists but no persona_call state yet — return a
            # zero-ed row rather than 404 so clients can poll safely
            # before the first turn.
            return StateResp(
                session_id=session_id,
                phase="opening",
                turn_index=0,
                skipped_how_are_you=False,
                asked_reason_fallback=False,
                reason_for_call="",
                pre_closing_trigger=None,
                recent_acks=[],
                recent_openers=[],
                recent_closings=[],
                caller_context={},
            )
        return StateResp(
            session_id=s["session_id"],
            phase=str(s.get("phase") or "opening"),
            turn_index=int(s.get("turn_index") or 0),
            skipped_how_are_you=bool(s.get("skipped_how_are_you")),
            asked_reason_fallback=bool(s.get("asked_reason_fallback")),
            reason_for_call=str(s.get("reason_for_call") or ""),
            pre_closing_trigger=s.get("pre_closing_trigger"),
            recent_acks=list(s.get("recent_acks") or []),
            recent_openers=list(s.get("recent_openers") or []),
            recent_closings=list(s.get("recent_closings") or []),
            caller_context=dict(s.get("caller_context") or {}),
        )

    @r.get("/last-directive/{session_id}", response_model=DirectiveResp)
    def get_last_directive(
        session_id: str,
        authorization: str = Header(default=""),
        homepilot_session: Optional[str] = Cookie(default=None),
    ):
        user = _resolve_user(authorization, homepilot_session)
        try:
            from ..voice_call.store import get_session_for_owner
            vc_row = get_session_for_owner(session_id, user["id"])
        except Exception:
            vc_row = None
        if vc_row is None:
            raise HTTPException(status_code=404, detail="Session not found")
        d = store.last_directive(session_id)
        if d is None:
            raise HTTPException(status_code=404, detail="No directive yet")
        return DirectiveResp(
            session_id=d["session_id"],
            turn_index=int(d["turn_index"]),
            phase=str(d["phase"]),
            applied=bool(d["applied"]),
            system_suffix=str(d["system_suffix"] or ""),
            post_directives=list(d["post_directives"] or []),
        )

    @r.post("/reset/{session_id}")
    def reset_session(
        session_id: str,
        authorization: str = Header(default=""),
        homepilot_session: Optional[str] = Cookie(default=None),
    ):
        """Wipe the anti-repetition ledgers for a session. Owner-bound.
        Used by QA + tests; harmless in production because the phase
        machine just starts fresh from 'opening'."""
        user = _resolve_user(authorization, homepilot_session)
        try:
            from ..voice_call.store import get_session_for_owner
            vc_row = get_session_for_owner(session_id, user["id"])
        except Exception:
            vc_row = None
        if vc_row is None:
            raise HTTPException(status_code=404, detail="Session not found")
        store.update_state(
            session_id,
            recent_acks=[],
            recent_openers=[],
            recent_closings=[],
        )
        return {"ok": True, "session_id": session_id}

    return r
