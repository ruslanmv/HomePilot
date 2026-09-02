"""Configuration for MeetingSense (design Part 1 §8, batches MS0).

Expressed the way HomePilot expresses configuration: one environment variable per
documented key, read through ``os.getenv``, same idiom as ``backend/app/config.py`` and
``backend/app/avatar_director/config.py``. ``backend/app/config.py`` itself is left alone —
this block is new keys in a new module, which is what "additive" means here.

Every flag ships off. ``MEETINGSENSE_ENABLED`` is the kill switch: while it is false the
status endpoint answers honestly and every other route refuses, and no meeting is recorded,
stored or transcribed.

**Six sub-flags, and none is implied by the master.** A batch that lands a capability lands
its flag off, so turning MeetingSense on never turns on something a later wave built. The
naming mirrors the waves in ``docs/design/MEETINGSENSE_BATCHES.md`` so an operator reading
the tracker and an operator reading ``.env`` see the same words.

Pure module: no FastAPI, no I/O, no side effects. That is what lets the config tests run
without the backend requirements installed, and it is why ``load_config()`` is a function
rather than module-level state — the tests set environment variables and call it again.
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


#: Retention modes, in increasing order of what is kept on disk. ``text`` is the default and
#: the only one that keeps nothing but words: no frames, no audio.
RETENTION_MODES = ("text", "text+frames", "all")


@dataclass(frozen=True)
class NotesConfig:
    """The rolling-notes engine (wave W4). ``interval_s`` is a floor, not a schedule: notes
    also fire on a word count, because a dense two minutes deserves an update and a quiet
    ten do not."""

    interval_s: int = 60
    max_words: int = 400
    model: str = ""


@dataclass(frozen=True)
class VisionConfig:
    """Slide captioning (wave W3). ``model`` empty means "use the multimodal default"; the
    keyframe path is still gated by whether a vision model exists at all."""

    model: str = ""
    max_keyframes_per_hour: int = 60


@dataclass(frozen=True)
class PanelsConfig:
    """Mirrors ``avatar_director.panels.DEFAULT_MAX_KB``. Both sides know the number; the
    server enforces it, because the server is the one that can refuse. A meeting card on the
    avatar surface is a summary projection for this reason — a long transcript is not a panel.
    """

    max_kb: int = 64


@dataclass(frozen=True)
class SubFlags:
    """One flag per wave beyond the recorder. All false, and none implied by ``enabled``."""

    remote: bool = False
    together: bool = False
    catalog: bool = False
    mcp: bool = False
    agent: bool = False
    modes: bool = False

    def as_dict(self) -> Dict[str, bool]:
        return {
            "remote": self.remote,
            "together": self.together,
            "catalog": self.catalog,
            "mcp": self.mcp,
            "agent": self.agent,
            "modes": self.modes,
        }


@dataclass(frozen=True)
class MeetingSenseConfig:
    """The whole MeetingSense block. Frozen: batches add keys, they do not rename them."""

    enabled: bool = False
    retention: str = "text"
    flags: SubFlags = field(default_factory=SubFlags)
    notes: NotesConfig = field(default_factory=NotesConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    panels: PanelsConfig = field(default_factory=PanelsConfig)

    def as_dict(self) -> Dict[str, Any]:
        """Flat view, for logging and for the test that asserts the key set is frozen."""
        return {
            "enabled": self.enabled,
            "retention": self.retention,
            "flags.remote": self.flags.remote,
            "flags.together": self.flags.together,
            "flags.catalog": self.flags.catalog,
            "flags.mcp": self.flags.mcp,
            "flags.agent": self.flags.agent,
            "flags.modes": self.flags.modes,
            "notes.interval_s": self.notes.interval_s,
            "notes.max_words": self.notes.max_words,
            "notes.model": self.notes.model,
            "vision.model": self.vision.model,
            "vision.max_keyframes_per_hour": self.vision.max_keyframes_per_hour,
            "panels.max_kb": self.panels.max_kb,
        }


def load_config() -> MeetingSenseConfig:
    """Build the config from the environment. Called per request by the status route and
    once per session later — never at import, so tests can vary the environment."""
    retention = os.getenv("MEETINGSENSE_RETENTION", "text").strip().lower() or "text"
    if retention not in RETENTION_MODES:
        # An unreadable retention setting must not silently keep *more* than the operator
        # asked for. Falling back to the strictest mode is the safe direction to be wrong in.
        retention = "text"

    return MeetingSenseConfig(
        enabled=_flag("MEETINGSENSE_ENABLED", False),
        retention=retention,
        flags=SubFlags(
            remote=_flag("MEETINGSENSE_REMOTE", False),
            together=_flag("MEETINGSENSE_TOGETHER", False),
            catalog=_flag("MEETINGSENSE_CATALOG", False),
            mcp=_flag("MEETINGSENSE_MCP", False),
            agent=_flag("MEETINGSENSE_AGENT", False),
            modes=_flag("MEETINGSENSE_MODES", False),
        ),
        notes=NotesConfig(
            interval_s=_int("MEETINGSENSE_NOTES_INTERVAL_S", 60),
            max_words=_int("MEETINGSENSE_NOTES_MAX_WORDS", 400),
            model=os.getenv("MEETINGSENSE_NOTES_MODEL", "").strip(),
        ),
        vision=VisionConfig(
            model=os.getenv("MEETINGSENSE_VISION_MODEL", "").strip(),
            max_keyframes_per_hour=_int("MEETINGSENSE_MAX_KEYFRAMES_PER_HOUR", 60),
        ),
        panels=PanelsConfig(max_kb=_int("MEETINGSENSE_PANEL_MAX_KB", 64)),
    )
