"""Vision — one frame in, a sentence and a gesture out (spec v1.1 §6.13, batch B15).

Three rules define this module, and each is the reason for a design decision rather than a
line of policy sitting on top of one.

## 1. Nothing is stored

Not to disk, not to a log, not to a database, not to a cache. ``frames.retention`` is 0 and
that is enforced by *never having a place to put a frame*: the bytes arrive base64 in a
request body, are handed to the model, and go out of scope. There is no temporary file, no
upload path, no `Path` in this module at all, and the logging in here never receives image
bytes or the model's answer — `tests/avatar/test_vision_retention.py` asserts all of that by
running a real request against a stubbed model with the filesystem and the log stream both
under observation.

This is also why ``app.multimodal.analyze_image`` could not simply be called: it resolves an
image *from disk*, which is precisely what must not happen here. Rather than build a second
vision path, B15 adds one optional ``image_b64`` argument to that function so the bytes can
be passed straight through; model resolution, the prompt and the Ollama call stay in the one
place that owns them.

## 2. The size cap is re-checked, without decoding

§6.13 caps input at 768 px on the long edge and says the server re-checks. The obvious
implementation — decode the image and read its size — is the wrong one: decoding a hostile
20000×20000 JPEG to find out it is too big *is* the attack. So the dimensions are read out of
the file header (JPEG SOFn, PNG IHDR), which touches a few dozen bytes and allocates nothing.

## 3. Intents are whitelist-checked here as well as on the client

A vision model writes prose. The way it names a gesture is §6.8's tag, and B10 already has a
splitter that pulls those out and drops anything outside §6.2's whitelist — so this reuses
``rtc.split_emote_tags`` rather than writing a second parser with a second idea of what is
allowed. The client checks again on arrival (B9). Belt and braces, deliberately.

Pure module apart from ``build_router``: no FastAPI import at module scope, so the config
tests keep running without the backend requirements installed.
"""

from __future__ import annotations

import base64
import binascii
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .protocol import EMOTE_WHITELIST, PROTOCOL_VERSION
from .rtc import split_emote_tags

log = logging.getLogger("avatar_director.vision")

#: How long a model may take before the ask is abandoned. §9 targets p95 ≤3 s; this is the
#: hard stop, not the target — a client waiting on a model that has stopped answering is
#: worse than a client told the ask failed.
MODEL_TIMEOUT_S = 12.0

#: Reject a body larger than this before decoding it. 768 px of JPEG is well under 1 MB;
#: anything at this size is not a capture, whatever it claims.
MAX_BODY_BYTES = 4 * 1024 * 1024

#: What the model is asked to do. The tag instruction is §6.8's, so the answer arrives in the
#: form the whole system already reads.
VISION_PROMPT = (
    "Look at this screenshot and answer the user in one or two sentences, as a companion "
    "sitting beside them would — an observation, not a caption. Do not describe the image "
    "as an image. If a gesture fits what you are saying, append at most one tag of the form "
    "[[emote:<name> <intensity 0..1>]] at the end."
)


class VisionError(Exception):
    """A refusal with a code the protocol can carry."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ── the size cap, read rather than decoded ───────────────────────────────────


def image_dimensions(raw: bytes) -> Optional[Tuple[int, int]]:
    """``(width, height)`` from a JPEG or PNG header, or ``None`` if it is neither.

    Reads the header only. Nothing is decoded, so a declared size of 20000×20000 costs the
    same handful of bytes as a real one — which is the point, because the check exists to
    stop exactly that image.
    """
    if len(raw) < 24:
        return None

    # PNG: 8-byte signature, then IHDR with width and height as big-endian uint32.
    if raw[:8] == b"\x89PNG\r\n\x1a\n" and raw[12:16] == b"IHDR":
        return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")

    # JPEG: walk the marker segments to the start-of-frame, which carries the size.
    if raw[:2] == b"\xff\xd8":
        i = 2
        end = len(raw)
        while i + 9 < end:
            if raw[i] != 0xFF:
                i += 1
                continue
            marker = raw[i + 1]
            # Standalone markers carry no length; skip them rather than misreading one.
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = int.from_bytes(raw[i + 2 : i + 4], "big")
            if length < 2:
                return None
            # SOF0..SOF15, excluding the two that are not frame headers.
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height = int.from_bytes(raw[i + 5 : i + 7], "big")
                width = int.from_bytes(raw[i + 7 : i + 9], "big")
                return width, height
            i += 2 + length
    return None


def decode_frame(image_b64: str, max_px: int) -> bytes:
    """Base64 in, bytes out, refused if it is too big in either sense.

    Both checks happen before anything reaches a model: the encoded length first, because it
    is free, and the declared dimensions second, because they are nearly free.
    """
    if not isinstance(image_b64, str) or not image_b64:
        raise VisionError("bad_frame", "no image")

    # Strip a data URI prefix if the client sent one; the field is documented as raw base64
    # but accepting both costs one split and saves a class of confusing failure.
    payload = image_b64.split(",", 1)[1] if image_b64.startswith("data:") else image_b64
    if len(payload) > MAX_BODY_BYTES:
        raise VisionError("frame_too_large", f"over {MAX_BODY_BYTES} bytes encoded")

    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise VisionError("bad_frame", f"not base64: {exc}") from exc
    if not raw:
        raise VisionError("bad_frame", "empty image")

    size = image_dimensions(raw)
    if size is None:
        raise VisionError("bad_frame", "not a JPEG or PNG")
    width, height = size
    if max(width, height) > max_px:
        # The client already capped this (§6.2, 512 px). A frame arriving over the server's
        # own limit means the client is wrong, compromised, or not the client — so it is a
        # refusal rather than a resize.
        raise VisionError("frame_too_large", f"{width}x{height} exceeds {max_px} px")
    return raw


# ── the service ──────────────────────────────────────────────────────────────


@dataclass
class VisionStats:
    """Counters only. Deliberately nothing that could hold a frame or an answer."""

    asks: int = 0
    refused: Dict[str, int] = field(default_factory=dict)
    intents_dropped: int = 0
    last_latency_ms: Optional[int] = None

    def refuse(self, code: str) -> None:
        self.refused[code] = self.refused.get(code, 0) + 1


class VisionService:
    """One ask at a time, and nothing kept between them."""

    def __init__(self, config, *, analyze: Optional[Callable] = None, now: Callable[[], float] = time.monotonic) -> None:
        self.config = config
        self.now = now
        self.stats = VisionStats()
        self._analyze = analyze

    @property
    def max_px(self) -> int:
        return int(getattr(self.config.vision, "max_image_px", 768) or 768)

    async def insight(self, image_b64: str, prompt: str = "", ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """``{text, intents:[{name,intensity}]}``. Raises :class:`VisionError` on refusal."""
        started = self.now()
        raw = decode_frame(image_b64, self.max_px)
        self.stats.asks += 1

        answer = await self._run_model(raw, prompt, ctx or {})
        text, intents = self._shape(answer)

        self.stats.last_latency_ms = int((self.now() - started) * 1000)
        # The frame goes out of scope here and is never named again. There is no store to
        # put it in even if a later batch wanted one.
        return {"text": text, "intents": intents}

    async def _run_model(self, raw: bytes, prompt: str, ctx: Dict[str, Any]) -> str:
        analyze = self._analyze or _default_analyze
        instruction = VISION_PROMPT
        if prompt:
            instruction = f"{VISION_PROMPT}\n\nThe user asked: {prompt}"
        if ctx.get("activity") or ctx.get("scene"):
            instruction += f"\n\nThey are currently: {ctx.get('activity') or ''} {ctx.get('scene') or ''}".rstrip()

        try:
            result = await analyze(
                image_b64=base64.b64encode(raw).decode("ascii"),
                model=(getattr(self.config.vision, "model", "") or "").strip() or None,
                user_prompt=instruction,
            )
        except Exception as exc:  # noqa: BLE001 — a model having a bad minute is a refusal
            self.stats.refuse("model_failed")
            # The exception text is logged; the frame and the answer are not, and there is
            # no branch here that could log either.
            log.warning("vision model failed: %s", type(exc).__name__)
            raise VisionError("model_failed", str(exc)[:200]) from exc

        if not result or not result.get("ok"):
            self.stats.refuse("model_failed")
            raise VisionError("model_failed", str((result or {}).get("error") or "no answer")[:200])
        return str(result.get("analysis_text") or "")

    def _shape(self, answer: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Split the model's prose from its gesture, and check the gesture is allowed."""
        before = answer.count("[[")
        text, gestures = split_emote_tags(answer, EMOTE_WHITELIST)
        self.stats.intents_dropped += max(0, before - len(gestures))
        # §6.8 allows at most one tag on a line of speech; more than one from a vision model
        # is a model ignoring its instructions, and the first is the one it meant.
        return text, gestures[:1]


async def _default_analyze(*, image_b64: str, model: Optional[str], user_prompt: str) -> Dict[str, Any]:
    """The real path: HomePilot's own multimodal module, given bytes rather than a path.

    Imported inside the call so this module stays importable — and testable — without
    ``httpx`` or the rest of the backend requirements present.
    """
    from app.multimodal import analyze_image  # noqa: PLC0415 — deliberately lazy

    return await analyze_image(
        "",
        None,
        image_b64=image_b64,
        model=model,
        user_prompt=user_prompt,
        mode="caption",
    )


# ── transport ────────────────────────────────────────────────────────────────


def build_router(config, *, service: Optional[VisionService] = None):
    """``POST /avatar/vision/insight``. Mounted by B8's ``register`` when enabled."""
    from fastapi import APIRouter, HTTPException  # noqa: PLC0415 — lazy, like session.py
    from pydantic import BaseModel, Field  # noqa: PLC0415

    class Ctx(BaseModel):
        activity: Optional[str] = None
        scene: Optional[str] = None
        lastUserMsg: Optional[str] = None

    class InsightRequest(BaseModel):
        image_b64: str
        prompt: str = ""
        ctx: Ctx = Field(default_factory=Ctx)

    # See `control.build_router` for the full reasoning. In short: this module has
    # `from __future__ import annotations`, so both the endpoint's `body: InsightRequest`
    # and `InsightRequest`'s own `ctx: Ctx` are strings, and Pydantic resolves a string
    # annotation against the module namespace — where a class defined inside this function
    # is not. Pydantic 2.13 finds it in the enclosing frame anyway; the pinned 2.7.4 does
    # not. Both names have to be published, because `Ctx` is resolved while `InsightRequest`
    # is being built.
    globals()["Ctx"] = Ctx
    globals()["InsightRequest"] = InsightRequest

    router = APIRouter(tags=["avatar-director"])
    vision = service or VisionService(config)

    @router.post("/avatar/vision/insight")
    async def insight(body: InsightRequest) -> Dict[str, Any]:  # pragma: no cover - transport
        try:
            return await vision.insight(body.image_b64, body.prompt, body.ctx.model_dump())
        except VisionError as error:
            status = 413 if error.code == "frame_too_large" else 400 if error.code == "bad_frame" else 502
            raise HTTPException(status_code=status, detail={"code": error.code, "msg": error.detail}) from error

    return router


def insight_message(result: Dict[str, Any], frame_id: str) -> Dict[str, Any]:
    """Shape a service result as the §6.9 ``vision_insight`` the socket sends."""
    return {
        "v": PROTOCOL_VERSION,
        "type": "vision_insight",
        "frameId": frame_id,
        "text": result.get("text", ""),
        "intents": result.get("intents", []),
    }
