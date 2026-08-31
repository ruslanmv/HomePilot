"""Configuration for the Avatar Director (spec v1.1 §6.2, addendum v1.2 §14.1).

The spec describes an ``avatar:`` section in "the existing config". HomePilot's config is
environment-variable based (``backend/app/config.py`` reads ``os.getenv`` at import time),
so the section is expressed the same way: one ``AVATAR_*`` variable per documented key,
same idiom, new keys only, and ``backend/app/config.py`` itself is left alone.

Every flag ships off. ``avatar.enabled`` is the kill switch from §1: while it is false,
B8's ``register()`` mounts no routes, and nothing in this package runs. ``adult.enabled``
is a second, independent gate — it is never implied by ``enabled``.

Pure module: no FastAPI, no I/O, no side effects, so it can be unit-tested (and read by a
reviewer) without the backend requirements installed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict


def _flag(name: str, default: bool = False) -> bool:
    """Read a boolean env var. Anything but a recognised true value is false."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


@dataclass(frozen=True)
class VisionConfig:
    """§6.13. ``retention`` is 0 and is re-checked server-side; frames are never stored."""

    model: str = ""
    max_image_px: int = 768


@dataclass(frozen=True)
class FramesConfig:
    retention: int = 0


@dataclass(frozen=True)
class CuriosityConfig:
    """§6.12. The per-session initiative budget: a companion that takes interest, never nags.

    ``min_gap_ms`` is the second half of the same idea. A budget of four spent in the first
    two minutes is still four interruptions in two minutes.
    """

    session_budget: int = 4
    min_gap_ms: int = 90000
    #: How long a session runs before she may raise anything of her own. Surfaced by the
    #: twenty-minute replay in ``curiosity_review.py``: with only a budget and a gap, she
    #: opened the evening fifteen seconds in with "Mum's scan results are due this week",
    #: which is the highest-curiosity thread and a terrible thing to be greeted with.
    min_session_age_ms: int = 120000


@dataclass(frozen=True)
class VoiceConfig:
    """§6.10, batch B10. The voice uplink is a third independent gate.

    ``media`` names where speech becomes text. ``transcript`` means the client's own
    recogniser does it and sends text up — the path that works today, because the client
    already has a recogniser and HomePilot already accepts final transcripts. ``webrtc``
    means the server terminates the media instead, which needs a media terminus installed;
    without one the server refuses the offer rather than accepting an offer it cannot honour.

    ``model`` is whatever the existing chat endpoint accepts (``persona:<id>``,
    ``personality:<id>``, a plain model name) — the uplink does not interpret it.
    """

    enabled: bool = False
    model: str = ""
    media: str = "transcript"


@dataclass(frozen=True)
class KbConfig:
    """Where the client's animation manifest is, for B17's read-only tools.

    The knowledge base is authored in the client repository alongside the assets it
    describes; copying it here would give two answers to "what can she do". Empty by
    default, and the two catalogue tools refuse by name rather than returning nothing.
    """

    manifest: str = ""


@dataclass(frozen=True)
class AdultConfig:
    """Addendum §16.2.

    ``provider`` names the verification plugin. ``owner-attest`` is the self-host default
    and B28 makes it refuse to load on a multi-user instance; distribution builds must
    configure a real provider. A client-side dialog is never sufficient and must not
    exist — the server attestation is the only path by which a client becomes verified.
    """

    enabled: bool = False
    provider: str = "owner-attest"


@dataclass(frozen=True)
class RedactionConfig:
    """Addendum §16.5. Memory writes in adult mode keep warmth signals, never explicit detail."""

    enabled: bool = True


@dataclass(frozen=True)
class AvatarDirectorConfig:
    """The whole ``avatar:`` section. Frozen: batches add keys, they do not rename them."""

    enabled: bool = False
    vision: VisionConfig = field(default_factory=VisionConfig)
    frames: FramesConfig = field(default_factory=FramesConfig)
    curiosity: CuriosityConfig = field(default_factory=CuriosityConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    kb: KbConfig = field(default_factory=KbConfig)
    adult: AdultConfig = field(default_factory=AdultConfig)
    redaction: RedactionConfig = field(default_factory=RedactionConfig)

    def as_dict(self) -> Dict[str, Any]:
        """Flat view for logging and for the tests that assert the key set is frozen."""
        return {
            "enabled": self.enabled,
            "vision.model": self.vision.model,
            "vision.max_image_px": self.vision.max_image_px,
            "frames.retention": self.frames.retention,
            "curiosity.session_budget": self.curiosity.session_budget,
            "curiosity.min_gap_ms": self.curiosity.min_gap_ms,
            "curiosity.min_session_age_ms": self.curiosity.min_session_age_ms,
            "voice.enabled": self.voice.enabled,
            "voice.model": self.voice.model,
            "voice.media": self.voice.media,
            "kb.manifest": self.kb.manifest,
            "adult.enabled": self.adult.enabled,
            "adult.provider": self.adult.provider,
            "redaction.enabled": self.redaction.enabled,
        }


def load_config() -> AvatarDirectorConfig:
    """Build the config from the environment. Called by B8's ``register()``, not at import."""
    return AvatarDirectorConfig(
        enabled=_flag("AVATAR_ENABLED", False),
        vision=VisionConfig(
            model=os.getenv("AVATAR_VISION_MODEL", "").strip(),
            max_image_px=_int("AVATAR_VISION_MAX_IMAGE_PX", 768),
        ),
        frames=FramesConfig(retention=_int("AVATAR_FRAMES_RETENTION", 0)),
        curiosity=CuriosityConfig(
            session_budget=_int("AVATAR_CURIOSITY_SESSION_BUDGET", 4),
            min_gap_ms=_int("AVATAR_CURIOSITY_MIN_GAP_MS", 90000),
            min_session_age_ms=_int("AVATAR_CURIOSITY_MIN_SESSION_AGE_MS", 120000),
        ),
        voice=VoiceConfig(
            enabled=_flag("AVATAR_VOICE_ENABLED", False),
            model=os.getenv("AVATAR_VOICE_MODEL", "").strip(),
            media=os.getenv("AVATAR_VOICE_MEDIA", "transcript").strip().lower() or "transcript",
        ),
        kb=KbConfig(manifest=os.getenv("AVATAR_KB_MANIFEST", "").strip()),
        adult=AdultConfig(
            enabled=_flag("AVATAR_ADULT_ENABLED", False),
            provider=os.getenv("AVATAR_ADULT_PROVIDER", "owner-attest").strip() or "owner-attest",
        ),
        redaction=RedactionConfig(enabled=_flag("AVATAR_REDACTION_ENABLED", True)),
    )
