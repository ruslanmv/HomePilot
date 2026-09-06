"""Measure the machine; never look it up (batch LS5).

The plan is blunt about this and it is worth repeating where the code is: **do not hard-code
which runtime is fastest on Intel, AMD or Apple from documentation. The benchmark decides.** A
table of "recommended device per vendor" is out of date the week after it is written, and it is
wrong on the machine in front of you for reasons no table can see — a mismatched ctranslate2
wheel, a laptop on battery, a GPU with three other things on it.

So this runs the model once against a short sample and writes down what happened:

```json
{"engine": "faster-whisper", "model": "whisper-large-v3-turbo",
 "device": "cuda", "compute": "float16", "rtf": 0.11, "tested_at": "…"}
```

Two details carry the batch.

**The device recorded is the device read back from the engine**, not the device asked for.
``auto`` falls back to CPU silently when CUDA is present but unusable, and an install running ten
times slower than its budget while the interface says GPU is worse than one that says CPU. That
is this batch's stated acceptance and it is invisible without reading the answer back.

**The real-time factor is measured, not estimated.** ``rtf`` is wall-clock seconds per second of
audio: 0.11 means eleven seconds of compute for a hundred of speech, and anything at or above 1.0
cannot keep up with a live meeting however good its transcript is.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .hardware import Hardware, detect
from .models import root

PROFILE_FILE = "profile.json"

#: Above this a machine cannot keep up with live speech, whatever the transcript looks like.
#: Not 1.0: transcription is not the only thing happening during a meeting, and a factor that
#: leaves nothing spare turns every hiccup into a backlog it never recovers from.
KEEPS_UP_RTF = 0.7

#: The choices a person is offered. Everything else is a measurement, not a preference.
PRESETS = ("auto", "accuracy", "low-memory", "advanced")


@dataclass
class Profile:
    """What was measured, and when."""

    engine: str = "faster-whisper"
    model: str = ""
    device: str = ""
    compute: str = ""
    #: Wall-clock seconds per second of audio. Lower is better; below `KEEPS_UP_RTF` keeps up.
    rtf: float = 0.0
    sample_s: float = 0.0
    elapsed_s: float = 0.0
    tested_at: str = ""
    hardware: Dict[str, Any] = field(default_factory=dict)
    #: Set when the run failed. A profile with an error is still a profile — "we tried and it
    #: did not load" is a fact worth keeping, and re-running it every startup is not.
    error: str = ""

    @property
    def keeps_up(self) -> bool:
        return bool(self.rtf) and self.rtf <= KEEPS_UP_RTF and not self.error

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["keeps_up"] = self.keeps_up
        return data


def path_for(environ=None) -> Path:
    return root(environ) / PROFILE_FILE


def load(environ=None) -> Optional[Profile]:
    """The stored profile, or ``None``. Never raises on a corrupt or half-written file."""
    try:
        raw = json.loads(path_for(environ).read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    known = {field_name for field_name in Profile.__dataclass_fields__}
    return Profile(**{key: value for key, value in raw.items() if key in known})


def store(profile: Profile, environ=None) -> Optional[Path]:
    """Write the profile beside the packs. Failure to write is not failure to transcribe."""
    target = path_for(environ)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(profile.as_dict(), indent=2), "utf-8")
        return target
    except OSError:
        return None


def candidates(hardware: Optional[Hardware] = None) -> List[Dict[str, str]]:
    """Configurations worth *trying*, best-first. Not a claim that any is faster.

    The ordering is a search order, and the benchmark is what turns it into an answer. On a
    machine where CUDA is present but broken, the first candidate simply measures badly — or
    reports CPU when asked for CUDA — and the second one wins on its numbers.
    """
    hardware = hardware or detect()
    out: List[Dict[str, str]] = []
    if hardware.cuda:
        out.append({"device": "cuda", "compute": "float16"})
        out.append({"device": "cuda", "compute": "int8_float16"})
    out.append({"device": "cpu", "compute": "int8"})
    return out


def measure(
    provider,
    sample: bytes,
    *,
    sample_s: float,
    fmt: str = "wav",
    now: Callable[[], float] = time.monotonic,
    hardware: Optional[Hardware] = None,
) -> Profile:
    """Run one clip through *provider* and write down what happened.

    Takes a provider rather than building one, so the same function measures the real engine and
    a stubbed one, and so nothing here has to know how a provider is constructed.
    """
    hardware = hardware or provider.hardware() if hasattr(provider, "hardware") else (hardware or detect())
    started = now()
    error = ""
    try:
        engine = provider.load()
        if engine is None:
            error = getattr(provider, "load_error", "") or "load-failed"
        else:
            provider._run(sample, fmt=fmt, word_timestamps=False, vad=False)
            error = getattr(provider, "load_error", "") or ""
    except Exception as exc:  # a benchmark that raises tells you nothing about the machine
        error = f"{type(exc).__name__}: {exc}"
    elapsed = max(0.0, now() - started)

    resolved = getattr(provider, "resolved", None)
    return Profile(
        engine="faster-whisper",
        model=(resolved.pack.id if resolved and resolved.pack else ""),
        # Read back, never echoed. The whole batch is this line.
        device=str(getattr(provider, "device", "") or ""),
        compute=str(getattr(provider, "compute", "") or ""),
        rtf=round(elapsed / sample_s, 4) if sample_s > 0 and not error else 0.0,
        sample_s=round(sample_s, 3),
        elapsed_s=round(elapsed, 4),
        tested_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        hardware=hardware.as_dict() if hardware else {},
        error=error,
    )


def ensure(provider, sample: bytes, *, sample_s: float, environ=None, force: bool = False, **kwargs) -> Profile:
    """The stored profile, measuring one first if there isn't one.

    Measured **once**, not per meeting: a benchmark that re-runs at every startup is a delay
    somebody pays for repeatedly and learns nothing new from.
    """
    if not force:
        existing = load(environ)
        if existing is not None:
            return existing
    profile = measure(provider, sample, sample_s=sample_s, **kwargs)
    store(profile, environ)
    return profile
