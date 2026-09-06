"""Try harder before giving up, and say the right thing when you do (batch V6).

```text
overview → nothing usable? → each crop on its own → a better installed model → only then, say so
```

The rung that does the work is the middle one, and it is worth being precise about why it works
today. V5's tiling sends several crops **in one request**, which needs a model that can reason
across images — so it is gated, and the gate is closed until V8 measures one. This ladder sends
the same crops **one at a time**, each its own ordinary single-image request. Every vision model
can read one image. So the thing that actually rescues an unreadable 4K screenshot — text at
close to native resolution — is available on today's hardware, with today's models, right now.

Two properties matter more than the ladder itself:

* **the best reply is never thrown away.** Every rung's output is kept and ranked. A rung that
  the judgement in ``usable.py`` calls unusable still beats nothing, so a wrong judgement costs
  a model call, never an answer;
* **the failures are not shown.** A person asked what was on their screen. They get an answer,
  or one sentence about what to install — never a transcript of four attempts.
"""

from __future__ import annotations

import base64
import os
import time
from typing import Any, Callable, Dict, List, Optional

from . import copy as _copy
from .usable import assess

#: Wall clock for the whole ladder. New rungs are not *started* past it; one already running is
#: allowed to finish, because killing a model mid-answer wastes the work and produces nothing.
BUDGET_ENV = "VISION_LADDER_BUDGET_S"
DEFAULT_BUDGET_S = 90.0

#: Crops to try, at most, in the second rung. Each is a full model call on a local machine.
MAX_CROPS_ENV = "VISION_LADDER_MAX_CROPS"
DEFAULT_MAX_CROPS = 4


def _budget(environ=None) -> float:
    try:
        return float((environ or os.environ).get(BUDGET_ENV) or DEFAULT_BUDGET_S)
    except (TypeError, ValueError):
        return DEFAULT_BUDGET_S


def _max_crops(environ=None) -> int:
    try:
        return max(0, int((environ or os.environ).get(MAX_CROPS_ENV) or DEFAULT_MAX_CROPS))
    except (TypeError, ValueError):
        return DEFAULT_MAX_CROPS


class _Attempt:
    """One rung's result, kept whether or not it was any good."""

    __slots__ = ("rung", "model", "text", "ok", "reason", "ms", "error")

    def __init__(self, rung: str, model: Optional[str], result: Dict[str, Any], ms: int):
        self.rung = rung
        self.model = (result.get("meta") or {}).get("model") or model
        self.text = str(result.get("analysis_text") or "").strip()
        self.error = result.get("error_code") or ("error" if not result.get("ok") else "")
        self.ok, self.reason = assess(self.text) if result.get("ok") else (False, self.error or "failed")
        self.ms = ms

    def record(self) -> Dict[str, Any]:
        return {
            "rung": self.rung,
            "model": self.model,
            "ok": self.ok,
            "reason": self.reason,
            "chars": len(self.text),
            "ms": self.ms,
        }


async def analyze_persistently(
    *,
    image_bytes: bytes,
    upload_path,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    user_prompt: Optional[str] = None,
    mode: str = "both",
    purpose: str = "screen",
    mime_type: str = "image/png",
    analyze: Optional[Callable[..., Any]] = None,
    installed: Optional[Callable[..., Any]] = None,
    environ=None,
    now: Callable[[], float] = time.monotonic,
) -> Dict[str, Any]:
    """Run the ladder. Returns ``analyze_image``'s shape, plus ``meta.ladder``.

    ``analyze`` and ``installed`` are injected so the rungs can be tested without an Ollama;
    they default to the real ones, imported lazily so this module stays importable on an install
    without ``httpx``.
    """
    if analyze is None:
        from ..multimodal import analyze_image as analyze  # noqa: PLC0415
    if installed is None:
        from ..multimodal import _detect_best_vision_model as _detect  # noqa: PLC0415

        async def installed(base):  # type: ignore[misc]
            return await _detect(base)

    from .. import vision_adapter  # noqa: PLC0415 — lazy, like the rest

    started = now()
    budget = _budget(environ)
    encoded = base64.b64encode(image_bytes or b"").decode("ascii")
    attempts: List[_Attempt] = []
    records: List[Dict[str, Any]] = []
    last: Dict[str, Any] = {}

    async def rung(name: str, *, tried_model: Optional[str], **kwargs) -> _Attempt:
        nonlocal last
        at = now()
        try:
            result = await analyze(
                image_url="",
                upload_path=upload_path,
                base_url=base_url,
                model=tried_model,
                mode=mode,
                purpose=purpose,
                **kwargs,
            )
        except Exception as exc:  # a rung that throws is a rung that failed, not a 500
            result = {"ok": False, "error": str(exc), "error_code": "rung_failed", "analysis_text": ""}
        attempt = _Attempt(name, tried_model, result, int((now() - at) * 1000))
        attempts.append(attempt)
        records.append(attempt.record())
        last = result
        return attempt

    # ── rung 1: the whole screen, as asked ──────────────────────────────────
    first = await rung("overview", tried_model=model, image_b64=encoded, user_prompt=user_prompt)
    if first.ok:
        return _answer(first, last, records)

    # ── rung 2: each crop on its own, at close to native resolution ─────────
    if now() - started < budget:
        pieces = vision_adapter.crops(image_bytes, mime_type=mime_type, purpose=purpose, mode=mode)[
            : _max_crops(environ)
        ]
        readings: List[str] = []
        for piece in pieces:
            if now() - started >= budget:
                records.append({"rung": f"crop:{piece.label}", "ok": False, "reason": "out-of-budget"})
                break
            crop = await rung(
                f"crop:{piece.label}",
                tried_model=first.model or model,
                image_b64=base64.b64encode(piece.data).decode("ascii"),
                user_prompt=_crop_prompt(user_prompt, piece.label),
            )
            if crop.ok:
                readings.append(f"[{piece.label}] {crop.text}")
        if readings:
            # Stitched, with each region named. A model reading four crops separately cannot
            # know they are one screen — saying where each reading came from is what lets the
            # person, and the chat model above, put them back together.
            joined = "\n\n".join(readings)
            return _answer(
                None, last, records, text=joined, rung="crops", model=first.model or model
            )

    # ── rung 3: a better model, if a better one is installed ────────────────
    if now() - started < budget:
        try:
            alternate = await installed(base_url)
        except Exception:
            alternate = None
        already = {a.model for a in attempts if a.model}
        if alternate and alternate not in already:
            retry = await rung(
                "alternate-model", tried_model=alternate, image_b64=encoded, user_prompt=user_prompt
            )
            if retry.ok:
                return _answer(retry, last, records)

    # ── rung 4: keep whatever was best, or say what to install ──────────────
    best = max(attempts, key=lambda a: (a.ok, len(a.text)), default=None)
    if best is not None and best.text:
        return _answer(best, last, records, degraded=True)

    tried = [a.model for a in attempts if a.model]
    meta = dict(last.get("meta") or {})
    meta["ladder"] = records
    if not tried:
        # No rung ever had a model to run: nothing installed can look at an image. That is a
        # different sentence from "I couldn't read it", and telling somebody their screenshot
        # was unreadable when the real answer is "install a vision model" wastes their evening.
        sentence = _copy.no_vision_model()
        code = "no_vision_model"
    else:
        sentence = _copy.could_not_read(suggestion=_suggest(tried), tried=tried)
        code = "vision_unreadable"
    return {
        "ok": False,
        "error_code": code,
        "error": sentence,
        "message": sentence,
        "analysis_text": "",
        "meta": meta,
    }


def _crop_prompt(user_prompt: Optional[str], label: str) -> str:
    """The same question, about one region, said so the model does not answer about a whole screen."""
    question = (user_prompt or "What do you see?").strip()
    return (
        f"{question}\n\n"
        f"This picture is the {label.replace('-', ' ')} region of a larger screen, shown close "
        "up. Describe and transcribe only what is in this picture, and do not guess at anything "
        "outside it."
    )


def _suggest(tried: List[str]) -> Optional[str]:
    """The best-ranked model that was *not* one of the ones that just failed.

    A suggestion to install what is already installed is worse than no suggestion: it reads as
    the product not knowing what it has.
    """
    try:
        from ..multimodal import VISION_PREFERENCE  # noqa: PLC0415
    except Exception:
        return None
    lowered = [name.lower() for name in tried if name]
    for candidate in VISION_PREFERENCE:
        if not any(candidate in name for name in lowered):
            return _tagged(candidate)
    return None


#: Preference entries are family names; a person needs something they can paste after
#: `ollama pull`. Only families with an unambiguous default tag are spelled out.
_TAGS = {
    "qwen3-vl": "qwen3-vl:8b",
    "qwen2.5vl": "qwen2.5vl:7b",
    "qwen2.5-vl": "qwen2.5vl:7b",
    "qwen2-vl": "qwen2-vl:7b",
    "minicpm-v": "minicpm-v",
    "gemma3": "gemma3:4b",
    "llama3.2-vision": "llama3.2-vision:11b",
    "llava": "llava:7b",
}


def _tagged(family: str) -> str:
    return _TAGS.get(family, family)


def _answer(
    attempt: Optional[_Attempt],
    last: Dict[str, Any],
    records: List[Dict[str, Any]],
    *,
    text: Optional[str] = None,
    rung: Optional[str] = None,
    model: Optional[str] = None,
    degraded: bool = False,
) -> Dict[str, Any]:
    """One successful shape, whichever rung produced it. The rungs below it are never shown."""
    meta = dict(last.get("meta") or {})
    meta["ladder"] = records
    meta["rung"] = rung or (attempt.rung if attempt else "")
    if model or (attempt and attempt.model):
        meta["model"] = model or (attempt.model if attempt else None)
    if degraded:
        # Recorded, not said out loud: the reply is the best thing anybody has, and prefixing it
        # with a disclaimer would make a usable answer read like a failure.
        meta["degraded"] = True
    return {
        "ok": True,
        "analysis_text": text if text is not None else (attempt.text if attempt else ""),
        "meta": meta,
    }
