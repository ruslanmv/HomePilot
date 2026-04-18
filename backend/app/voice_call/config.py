"""
voice_call runtime configuration.

Every knob is an environment variable with a safe default. The feature
ships **off by default** — set ``VOICE_CALL_ENABLED=true`` to opt in.

Privacy defaults are deliberately conservative per the review note
("treat storage/privacy as first-class from day 1"):
- ``VOICE_CALL_STORE_TRANSCRIPTS`` defaults to ``false``.
- Metadata persistence (sessions + events) is enabled by default, but
  events only record event *types*, not full audio or raw user text.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class VoiceCallConfig:
    """Resolved runtime knobs. Immutable; re-import to refresh in tests."""

    # Master flag. When false, ``router.build_router()`` returns an empty
    # router and ``store.migrate()`` is a no-op — the feature is entirely
    # latent.
    enabled: bool

    # WebSocket transport for the turn bridge. Off => HTTP-only polling
    # fallback (not yet implemented, so if disabled the feature is
    # effectively off even if ``enabled`` is true).
    websocket_enabled: bool

    # Provider strategy. Only "internal" is wired at MVP; the string is
    # reserved for future external-realtime adapters.
    provider: str

    # Policy caps (server-enforced — never trust the client).
    max_duration_sec: int
    idle_timeout_sec: int
    resume_window_sec: int
    max_concurrent_per_user: int
    session_create_rate_per_min: int

    # Privacy. Turn transcripts are NOT persisted by default.
    store_transcripts: bool
    artifact_retention_days: int

    # Phase 2 + 3 streaming (token-level LLM streaming + barge-in).
    # Defaults off — when false, every byte on the wire and every
    # code path taken is identical to today. Independent of
    # ``enabled`` / ``websocket_enabled`` so the streaming path
    # can be dark-shipped alongside unary turns for measurement.
    streaming_enabled: bool
    # Barge-in is an optional sub-feature of streaming; can be
    # disabled independently if the VAD tap is misbehaving on a
    # given deployment.
    barge_in_enabled: bool


def load() -> VoiceCallConfig:
    """Resolve config from env vars every call. Cheap; keep fresh for tests."""
    return VoiceCallConfig(
        enabled=_bool_env("VOICE_CALL_ENABLED", False),
        websocket_enabled=_bool_env("VOICE_CALL_WEBSOCKET_ENABLED", True),
        provider=os.getenv("VOICE_CALL_PROVIDER", "internal").strip() or "internal",
        max_duration_sec=_int_env("VOICE_CALL_MAX_DURATION_SEC", 45 * 60),
        idle_timeout_sec=_int_env("VOICE_CALL_IDLE_TIMEOUT_SEC", 30),
        resume_window_sec=_int_env("VOICE_CALL_RESUME_WINDOW_SEC", 20),
        max_concurrent_per_user=_int_env("VOICE_CALL_MAX_CONCURRENT", 2),
        session_create_rate_per_min=_int_env("VOICE_CALL_CREATE_RATE", 10),
        store_transcripts=_bool_env("VOICE_CALL_STORE_TRANSCRIPTS", False),
        artifact_retention_days=_int_env("VOICE_CALL_ARTIFACT_TTL_DAYS", 30),
        streaming_enabled=_bool_env("VOICE_CALL_STREAMING_ENABLED", False),
        barge_in_enabled=_bool_env("VOICE_CALL_BARGE_IN_ENABLED", True),
    )
