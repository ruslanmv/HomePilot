"""Speaking into the meeting: tier-3 TTS and the virtual microphone (MS27, W9).

Practice needs the assistant's voice to reach the *call*, not the user's speakers. A browser
tab cannot do that: it can play audio, and the meeting's microphone will not hear it unless the
operating system is routing it there. So this is **desktop only**, and the routing is a virtual
audio device the user installs — VB-Cable on Windows, BlackHole on macOS, a null sink on Linux.

**The refusal is honest and specific.** On a hosted page or in a browser, `capability()` says
so and names the reason. It does not fall back to playing through the speakers: a rehearsal
partner audible in the room but not in the call is a feature that appears to work and does not,
which is worse than one that says it needs a driver.

**Nothing is installed for the user.** The wizard tells them what to install and then *checks*,
because a setup step that reports success without verifying is how somebody ends up in a mock
interview with no sound. `detect` is the check.
"""

from __future__ import annotations

import logging
import os
import platform
import re
from typing import Any, Dict, List, Optional, Sequence

log = logging.getLogger(__name__)

#: What a virtual audio device is called on each platform. Matched case-insensitively against
#: whatever device list the desktop app reports.
DEVICES: Dict[str, Dict[str, Any]] = {
    "Windows": {
        "names": ("cable input", "vb-audio", "vb-cable", "voicemeeter"),
        "product": "VB-Cable",
        "url": "https://vb-audio.com/Cable/",
        "steps": (
            "Download VB-Cable and run the installer as Administrator.",
            "Restart the machine — Windows does not load the driver until you do.",
            "In your meeting app, set the microphone to 'CABLE Output'.",
        ),
    },
    "Darwin": {
        "names": ("blackhole", "loopback", "soundflower"),
        "product": "BlackHole",
        "url": "https://existential.audio/blackhole/",
        "steps": (
            "Install BlackHole (2ch) and allow the system extension when macOS asks.",
            "Open Audio MIDI Setup and create a Multi-Output Device with BlackHole and "
            "your speakers, so you can hear the rehearsal too.",
            "In your meeting app, set the microphone to 'BlackHole 2ch'.",
        ),
    },
    "Linux": {
        "names": ("null sink", "virtual_mic", "pulse", "pipewire"),
        "product": "a PulseAudio/PipeWire null sink",
        "url": "https://wiki.archlinux.org/title/PipeWire",
        "steps": (
            "Create a null sink: pactl load-module module-null-sink "
            "sink_name=virtual_mic sink_properties=device.description=virtual_mic",
            "Create the loopback: pactl load-module module-remap-source "
            "master=virtual_mic.monitor source_name=virtual_mic",
            "In your meeting app, set the microphone to 'virtual_mic'.",
        ),
    },
}


def _os_name() -> str:
    return platform.system() or "Linux"


def guide(system: Optional[str] = None) -> Dict[str, Any]:
    """What to install on this platform, and how. Never raises.

    An unknown platform gets the Linux instructions, which is the honest default: anything that
    is not Windows or macOS and is running this is running something PulseAudio-shaped.
    """
    key = system or _os_name()
    spec = DEVICES.get(key) or DEVICES["Linux"]
    return {"system": key, "product": spec["product"], "url": spec["url"],
            "steps": list(spec["steps"])}


def detect(devices: Sequence[str], *, system: Optional[str] = None) -> Optional[str]:
    """The virtual device in this list, or ``None``.

    `devices` is what the desktop app enumerated. Injected rather than enumerated here because
    the backend has no audio stack and should not grow one — and because a test of "did we
    recognise the device" should not need a driver installed.
    """
    spec = DEVICES.get(system or _os_name()) or DEVICES["Linux"]
    for name in devices or ():
        label = str(name or "").strip()
        # No blank-name guard: every marker below is a non-empty string, so a blank label
        # cannot match one. A guard that can never fire is a line a reader has to rule out.
        if any(marker in label.lower() for marker in spec["names"]):
            return label
    return None


def capability(
    *,
    desktop: bool = False,
    devices: Sequence[str] = (),
    system: Optional[str] = None,
) -> Dict[str, Any]:
    """Can this install speak into a meeting, and if not, why not.

    One shape with a named reason rather than a bare boolean, for the reason MS0's status route
    gives: a client told "no" without being told which "no" cannot say anything useful, and the
    two nos here need completely different things from the user — a different app, or a driver.
    """
    if not desktop:
        return {"ok": False, "reason": "browser",
                "detail": "Speaking into a meeting needs the desktop app: a browser tab cannot "
                          "put audio into the microphone your meeting is listening to."}
    found = detect(devices, system=system)
    if not found:
        info = guide(system)
        return {"ok": False, "reason": "no_virtual_device",
                "detail": f"No virtual audio device found. Install {info['product']} and set "
                          "your meeting app's microphone to it.",
                "guide": info}
    return {"ok": True, "device": found}


# ── synthesis ───────────────────────────────────────────────────────────────

#: Words one spoken turn may carry. A rehearsal partner that monologues is one the user cannot
#: practise against, and a long synth is a long silence before anything is heard.
MAX_SPOKEN_WORDS = 120


def speakable(text: str) -> str:
    """The text as it should be spoken, or ``""``.

    Citations are stripped. MS13 asks for `[hh:mm:ss]` on anything quoted, which is exactly
    right on a card and unreadable out loud — a rehearsal partner that says "bracket zero zero
    twelve thirty bracket" is not one anybody practises against twice.
    """
    body = re.sub(r"\[\d{1,2}:\d{2}:\d{2}\]", "", text or "").strip()
    body = re.sub(r"\s{2,}", " ", body)
    if not body:
        return ""
    words = body.split()
    if len(words) > MAX_SPOKEN_WORDS:
        return " ".join(words[:MAX_SPOKEN_WORDS])
    return body


async def synth(
    text: str,
    *,
    provider: Any = None,
    premium: bool = True,
) -> Optional[bytes]:
    """Text → audio, through `voice/providers.py`. ``None`` when there is nothing to say.

    **Tier 3 is a server-side choice, exactly as `providers.py` says.** `get_tts_provider`
    takes an entitlement and returns the neural voice when one is configured; this passes that
    through and picks nothing itself. A MeetingSense-specific voice selection would be a second
    place deciding what a user is entitled to, which is the shape of every entitlement bug.
    """
    body = speakable(text)
    if not body:
        return None
    engine = provider
    if engine is None:
        try:
            from ...voice.providers import get_tts_provider

            engine = get_tts_provider(premium)
        except Exception:  # noqa: BLE001 — an install with no voice stack cannot speak
            log.debug("meetingsense: no TTS provider available", exc_info=True)
            return None
    try:
        return await engine.synth(body)
    except Exception:  # noqa: BLE001 — a failed synth is never worth the rehearsal
        log.exception("meetingsense: TTS failed")
        return None
