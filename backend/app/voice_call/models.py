"""
voice_call request / response / event schemas.

Kept small on purpose: the public surface is half a dozen shapes. If a
new field is needed, add it optional so the client stays forward-
compatible with older backends (same rule the rest of HomePilot follows).
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


EntryMode = Literal["header_button", "long_press", "hint_tap", "resume"]

SessionStatus = Literal[
    "connecting",
    "live",
    "interrupted",  # WS dropped, within resume window
    "ending",
    "ended",
]


class DeviceInfo(BaseModel):
    platform: Optional[str] = None      # "web" / "ios" / "android" / "desktop"
    app_version: Optional[str] = None


class CreateSessionReq(BaseModel):
    conversation_id: Optional[str] = None
    persona_id: Optional[str] = None
    entry_mode: EntryMode = "header_button"
    device_info: DeviceInfo = Field(default_factory=DeviceInfo)


class Capabilities(BaseModel):
    """What the server promises this session can do. Keep truthful — any
    false promise here turns into a UX bug users feel immediately."""
    # At MVP turn-based only. Full duplex (true barge-in) reads as false
    # until we add server-side audio, per the review note.
    interruptions: bool = False
    barge_in: bool = False
    # Assistant replies come as ``transcript.final`` only — no partials.
    # This matches the current ``/v1/chat/completions`` behavior which
    # rejects streaming with a 501 (openai_compat_endpoint.py:477).
    transcript_live: bool = False


class CreateSessionResp(BaseModel):
    session_id: str
    ws_url: str
    resume_token: str        # short-lived; only accepted by ws handshake
    expires_at: int          # epoch ms; WS must open before this
    max_duration_sec: int
    capabilities: Capabilities


class Session(BaseModel):
    """Public session record. Mirrors the DB row without resume_token or
    raw payloads, so an accidental log of this shape never leaks
    credentials."""
    id: str
    user_id: str
    conversation_id: Optional[str] = None
    persona_id: Optional[str] = None
    entry_mode: EntryMode
    status: SessionStatus
    started_at: int
    ended_at: Optional[int] = None
    ended_reason: Optional[str] = None
    duration_sec: Optional[int] = None


class EndSessionResp(BaseModel):
    session_id: str
    status: SessionStatus
    ended_at: int
    ended_reason: str
    duration_sec: int


class HintsResp(BaseModel):
    """Discoverability copy + timings. Server is the source of truth so
    the product team can tune thresholds without a frontend ship."""
    hint_enabled: bool = True
    show_on_mic_tap: bool = True
    auto_hide_ms: int = 1400
    hold_threshold_ms: int = 220
    # Which entry modes this build accepts. Lets us A/B or disable a
    # mode without a client change.
    accepted_entry_modes: List[EntryMode] = Field(
        default_factory=lambda: ["header_button", "long_press", "hint_tap"]
    )


# ── WebSocket event envelope ──────────────────────────────────────────

class WsEvent(BaseModel):
    """Every message over the WS — both directions — wraps into this.

    ``seq`` is monotonic per session for events the server originates;
    client-originated events don't need it (server ignores it if set).
    """
    type: str
    seq: Optional[int] = None
    ts: Optional[int] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
