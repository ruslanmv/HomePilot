"""What this machine will and will not do about remote screen capture (batch RS1).

Every value is read at call time, never at import. A capture setting that can only be
changed by restarting the process is a setting nobody changes, and the tests need to flip
these between cases.

The one that matters is :func:`headless_allowed`. Path A — grabbing a still from a screen
share the user has already granted in a HomePilot tab — needs no flag, because the consent
and the always-visible browser indicator are already there. Path B takes a picture of the
desktop with no browser grant and no indicator of its own, so it stays off until somebody
sets ``HOMEPILOT_REMOTE_CAPTURE=true`` **on the machine being photographed**. It is
deliberately not settable from the cloud, from the chat, or over any route in this package.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..config import UPLOAD_DIR


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _num(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


def headless_allowed() -> bool:
    """May this process photograph the desktop with no browser grant? Default no."""
    return _flag("HOMEPILOT_REMOTE_CAPTURE")


def device_name() -> str:
    """What the user calls this computer. Shown on every card, so it is worth setting."""
    name = os.getenv("HOMEPILOT_DEVICE_NAME", "").strip()
    if name:
        return name
    try:
        import socket

        host = socket.gethostname().split(".")[0].strip()
    except Exception:
        host = ""
    return host or "This computer"


def frame_ttl_s() -> float:
    """How long a captured frame stays readable. Ten minutes, matching the client handle."""
    return max(30.0, _num("HOMEPILOT_REMOTE_CAPTURE_TTL_S", 600.0))


def min_interval_s() -> float:
    """Floor between two captures. Turns a runaway caller into a refusal, not a camera."""
    return max(0.0, _num("HOMEPILOT_REMOTE_CAPTURE_MIN_INTERVAL_S", 3.0))


def hourly_cap() -> int:
    """Hard ceiling per rolling hour. Zero would mean "never", so it is floored at one."""
    return max(1, int(_num("HOMEPILOT_REMOTE_CAPTURE_HOURLY_CAP", 120)))


def agent_wait_s() -> float:
    """How long a capture waits for a HomePilot tab to answer before giving up on path A."""
    return max(1.0, _num("HOMEPILOT_REMOTE_CAPTURE_AGENT_WAIT_S", 12.0))


def agent_fresh_s() -> float:
    """A tab that has not polled within this long is not there. Absence means no."""
    return max(5.0, _num("HOMEPILOT_REMOTE_CAPTURE_AGENT_FRESH_S", 60.0))


def frames_dir() -> Path:
    """Frames live in their own subdirectory of ``UPLOAD_DIR``.

    Their own, not the flat upload root, for one reason: the sweep in :mod:`.frames` deletes
    by age, and it must never be pointed at a directory holding anything a user meant to
    keep. A screenshot of somebody's desktop is the most disposable file HomePilot writes.
    """
    path = Path(UPLOAD_DIR) / "screensense"
    path.mkdir(parents=True, exist_ok=True)
    return path


def audit_path() -> Path:
    """Local, append-only record of every headless capture. Never served over HTTP."""
    return frames_dir().parent / "screensense-audit.log"
