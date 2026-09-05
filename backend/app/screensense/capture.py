"""Path B: photographing the desktop with no browser in the way (batch RS1).

This is the mechanism that makes remote capture work on a machine with nothing open, and it
is also the one with a real cost: it can take a picture with no browser grant and no sharing
indicator. So it is off unless somebody sets ``HOMEPILOT_REMOTE_CAPTURE=true`` **on this
machine**, it is rate limited in two directions, and every single capture is written to a
local append-only log the user can read.

The screen grab itself is optional-import all the way down. A machine without ``mss`` and
without Pillow reports "no mechanism" and the feature says so in words; it does not install
anything, and it does not crash the process that imports this module.
"""

from __future__ import annotations

import io
import time
from typing import List, Optional, Tuple

from . import config

#: Rolling record of capture times, newest last. Trimmed to the hour on every check.
_history: List[float] = []


# ── what this machine can actually do ──────────────────────────────────────


def _mss_available() -> bool:
    try:
        import mss  # noqa: F401
    except Exception:
        return False
    return True


def _pil_available() -> bool:
    """Pillow's core, which every path needs — it is what turns a grab into a JPEG."""
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        return False
    return True


def _pillow_grab_available() -> bool:
    """``ImageGrab`` is not everywhere Pillow is — it is absent on a headless Linux."""
    try:
        from PIL import ImageGrab  # noqa: F401
    except Exception:
        return False
    return True


def backend_name() -> Optional[str]:
    """Which desktop grabber is usable here, or ``None``. Reported, never guessed at.

    Pillow gates both answers because both end in :func:`_encode`. Reporting ``mss`` on a
    machine that cannot encode a JPEG would move the failure from a sentence the user can
    read to a traceback in a log they cannot.
    """
    if not _pil_available():
        return None
    if _mss_available():
        return "mss"
    if _pillow_grab_available():
        return "pillow"
    return None


# ── the two gates ──────────────────────────────────────────────────────────


def _trim(now: float) -> None:
    cutoff = now - 3600.0
    while _history and _history[0] < cutoff:
        _history.pop(0)


def rate_check(now: Optional[float] = None) -> Optional[str]:
    """``None`` when a capture may proceed, else why it may not, in words.

    Two limits with two different jobs: the interval stops a loop from turning this into a
    video feed, and the hourly cap stops a patient loop from doing the same thing slowly.
    """
    when = now if now is not None else time.time()
    _trim(when)
    if _history and (when - _history[-1]) < config.min_interval_s():
        wait = config.min_interval_s() - (when - _history[-1])
        return f"Too soon — one screenshot every {config.min_interval_s():.0f}s. Try again in {wait:.0f}s."
    if len(_history) >= config.hourly_cap():
        return f"Hourly limit reached ({config.hourly_cap()} screenshots). It resets as the hour rolls."
    return None


def record(mechanism: str, now: Optional[float] = None) -> None:
    """Count a capture against the limits and write it to the local audit log.

    Both mechanisms are counted, not just the headless one: the rate limit exists to stop
    this from becoming a stream, and a stream of tab-captured frames is just as much a
    stream. Only headless captures are *logged*, because those are the ones with no
    indicator of their own — a share the user is watching in their own browser bar does not
    need a line in a file to be visible.
    """
    when = now if now is not None else time.time()
    _trim(when)
    _history.append(when)
    if mechanism != "desktop":
        return
    try:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(when))
        with config.audit_path().open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp}\tdesktop-capture\t{config.device_name()}\n")
    except OSError:
        # A log that cannot be written must not stop the user getting their screenshot.
        pass


def reset() -> None:
    """Forget the rate-limit history. Tests only."""
    _history.clear()


# ── the grab ───────────────────────────────────────────────────────────────


def _encode(image, max_width: int) -> Optional[bytes]:
    """A PIL image → downscaled JPEG bytes, or ``None`` if Pillow cannot encode."""
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        return None
    width, height = image.size
    if width > max_width and width > 0:
        scale = max_width / float(width)
        image = image.resize((max_width, max(1, int(height * scale))))
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=82)
    return buffer.getvalue()


def grab(max_width: int = 1280) -> Tuple[Optional[bytes], str]:
    """One JPEG of the primary display, or ``(None, why)``.

    Returns the reason rather than raising because every caller of this wants to *say* what
    went wrong. "Remote screen viewing is off on Home PC" is a sentence a person can act on;
    an ImportError traceback is not.
    """
    if not config.headless_allowed():
        return None, "disabled"
    backend = backend_name()
    if backend is None:
        return None, "no-backend"
    try:
        if backend == "mss":
            import mss
            from PIL import Image

            with mss.mss() as sct:
                shot = sct.grab(sct.monitors[0])
            image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        else:
            from PIL import ImageGrab

            image = ImageGrab.grab()
        data = _encode(image, max_width)
        if not data:
            return None, "encode-failed"
        return data, "ok"
    except Exception as exc:  # a headless X server, a Wayland refusal, a locked screen
        return None, f"capture-failed: {exc}"
