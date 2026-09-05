"""Remote screen capture over HTTP (batch RS1).

Five routes, and the interesting one is :func:`capability`, which always answers 200 even
when nothing here can take a picture. That is the same rule MeetingSense's status route
keeps, for the same reason: a client has to tell "this HomePilot is too old to know what you
are asking" from "capture is switched off on that machine" from "ready", and a 404 collapses
all three into a shrug. Each of those has a different sentence for the user and a different
fix, so each gets a distinct answer here.

Order of attempts inside :func:`capture` is the whole consent story:

  1. a HomePilot tab holding a share the user granted and can see — no new permission;
  2. a headless desktop grab — only behind the local flag;
  3. a refusal that names which of the two was missing.

Never the other way round. Path B is capable of satisfying every request path A could, and
if it ran first the browser's sharing indicator would stop being the thing that tells the
user a picture was taken.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from ..auth import require_api_key
from . import broker, capture as capture_mod, config, frames

log = logging.getLogger(__name__)

router = APIRouter(tags=["screensense"], dependencies=[Depends(require_api_key)])

#: Ceiling on the frame a tab may post back. A screenshot is well under this; anything above
#: it is not a screenshot, and reading it into memory to find that out is the bug.
MAX_FRAME_BYTES = 8 * 1024 * 1024


def _capability() -> Dict[str, Any]:
    backend = capture_mod.backend_name()
    share = broker.agent_present()
    headless = config.headless_allowed() and backend is not None
    if share or headless:
        reason = "ok"
    elif not config.headless_allowed():
        reason = "disabled"
    else:
        reason = "no-backend"
    return {
        "ok": True,
        "device": config.device_name(),
        # Mechanisms, in the order `capture` will try them. An empty list is a complete and
        # honest answer, and the client turns it into a sentence rather than a spinner.
        "mechanisms": ([{"kind": "share"}] if share else []) + ([{"kind": "desktop", "backend": backend}] if headless else []),
        "available": bool(share or headless),
        "reason": reason,
        "headless_allowed": config.headless_allowed(),
        "headless_backend": backend,
        "share_agent": {"present": share, "last_seen_s": round(broker.last_seen(), 1)},
        "ttl_s": config.frame_ttl_s(),
        "min_interval_s": config.min_interval_s(),
        "hourly_cap": config.hourly_cap(),
    }


@router.get("/v1/screensense/capability")
async def capability() -> JSONResponse:
    """What this machine will do about a remote screenshot, right now. Always 200."""
    return JSONResponse(status_code=200, content=_capability())


class CaptureIn(BaseModel):
    """Why the picture is being taken, and how big it needs to be."""

    reason: Optional[str] = Field(None, description="Shown to the user on the sharing tab")
    max_width: Optional[int] = Field(1280, ge=160, le=3840)


@router.post("/v1/screensense/capture")
async def capture(inp: Optional[CaptureIn] = None) -> JSONResponse:
    """Take one still and return a handle to it.

    One JPEG per call. There is no streaming variant of this route and there should not be:
    the user has to be able to say which picture the assistant is talking about, and that is
    only true while pictures arrive one at a time, on request.
    """
    body = inp or CaptureIn()
    denied = capture_mod.rate_check()
    if denied:
        return JSONResponse(
            status_code=429,
            content={"ok": False, "error": "rate-limited", "message": denied, **_capability()},
        )

    # 1. The tab the user is already sharing from.
    data = await broker.request(body.reason or "")
    mechanism = "share"

    # 2. The desktop, if this machine has been told that is allowed.
    if not data:
        data, why = capture_mod.grab(int(body.max_width or 1280))
        mechanism = "desktop"
        if not data:
            cap = _capability()
            return JSONResponse(
                status_code=409,
                content={"ok": False, "error": why, "message": _explain(why, cap), **cap},
            )

    if len(data) > MAX_FRAME_BYTES:
        return JSONResponse(
            status_code=413,
            content={"ok": False, "error": "frame-too-large", "message": "That screenshot came back far larger than a screenshot should be."},
        )

    frame = frames.store(data, mechanism)
    capture_mod.record(mechanism)
    return JSONResponse(status_code=200, content={"ok": True, "frame": frame.handle()})


def _explain(why: str, cap: Dict[str, Any]) -> str:
    """A refusal in words the person reading it can act on, naming the machine.

    Each branch names *where* the fix is. "Turn it on" is useless advice when the user is
    looking at a different computer than the one that has to change.
    """
    device = cap.get("device") or "that computer"
    if why == "disabled":
        return (
            f"Remote screen viewing is off on {device}. Turn it on in HomePilot on that "
            "computer, or share your screen there and I can look at what you are sharing."
        )
    if why == "no-backend":
        return (
            f"{device} allows remote screen viewing, but has no way to take the picture. "
            "Install the screenshot support (mss and Pillow) on that computer."
        )
    if why.startswith("capture-failed"):
        return f"{device} could not take the screenshot just then. {why.split(': ', 1)[-1]}"
    if why == "encode-failed":
        return f"{device} took the screenshot but could not turn it into an image."
    return f"{device} could not take a screenshot."


@router.get("/v1/screensense/frame/{frame_id}")
async def frame(frame_id: str) -> Response:
    """The bytes. 404 once the frame has expired, whether or not the sweep has run yet.

    ``no-store`` rather than a short max-age: a screenshot of somebody's desktop must not sit
    in a disk cache after the copy on this machine has been deleted.
    """
    found = frames.get(frame_id)
    if found is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "expired-or-unknown"})
    try:
        data = found.path.read_bytes()
    except OSError:
        frames.drop(frame_id)
        return JSONResponse(status_code=404, content={"ok": False, "error": "expired-or-unknown"})
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "X-Frame-Expires-In": str(int(found.handle()["expires_in_s"])),
        },
    )


def _default_vision_model() -> str:
    """The vision model this machine is configured to use, or ``""`` for auto-detection.

    RS1's caller is a browser on somebody else's machine, so it cannot know what this
    HomePilot's Settings say — its own ``localStorage`` belongs to a different install. The
    honest server-side equivalent is the environment, and ``MULTIMODAL_MODEL`` is the variable
    MeetingSense's own vision capability already reads.

    Empty means empty: a blank variable falls through to auto-detection rather than being sent
    as a model named ``""``.
    """
    return os.getenv("MULTIMODAL_MODEL", "").strip()


def _default_vision_base_url() -> str:
    """Where that model lives. Blank leaves ``multimodal`` on its own ``OLLAMA_BASE_URL``."""
    return os.getenv("MULTIMODAL_BASE_URL", "").strip()


class ExplainIn(BaseModel):
    """Ask the vision model about a frame that was already captured."""

    frame_id: str = Field(..., description="A handle returned by /v1/screensense/capture")
    question: Optional[str] = Field(None, description="What the user actually asked")
    model: Optional[str] = Field(None, description="Vision model override")
    base_url: Optional[str] = Field(None, description="Provider base URL override")


#: Wrapped around whatever the user asked. Without it a small vision model answers a
#: screenshot question with a caption of a photograph — "a computer screen on a desk".
_FRAME_PROMPT = (
    " — You are looking at a screenshot of the user's own computer screen. Answer as a "
    "desk-side assistant: name the concrete thing on screen the question is about, quote any "
    "error text exactly, and stay under 120 words."
)


@router.post("/v1/screensense/explain")
async def explain(inp: ExplainIn) -> JSONResponse:
    """Run the vision model over one *already captured* frame.

    This route exists so that "what can you see?" is answered about the picture the user is
    looking at. Capturing again would be easier and is the bug: the assistant would describe
    a screen that has moved on, under a card showing the one it has not, and nothing on
    either would say they differ.

    The bytes go straight to the model as base64. Nothing is re-uploaded, no second copy is
    written, and the frame's TTL still governs — an expired frame is a 404 here too.
    """
    found = frames.get(inp.frame_id)
    if found is None:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": "expired-or-unknown", "message": "That screenshot has expired. Ask me to take another."},
        )
    try:
        data = found.path.read_bytes()
    except OSError:
        frames.drop(inp.frame_id)
        return JSONResponse(status_code=404, content={"ok": False, "error": "expired-or-unknown"})

    try:
        from pathlib import Path as _Path

        from ..config import UPLOAD_DIR
        from ..multimodal import analyze_image

        result = await analyze_image(
            image_url="",
            upload_path=_Path(UPLOAD_DIR),
            base_url=inp.base_url or _default_vision_base_url(),
            model=inp.model or _default_vision_model(),
            user_prompt=(inp.question or "What do you see?") + _FRAME_PROMPT,
            mode="both",
            image_b64=base64.b64encode(data).decode("ascii"),
        )
    except Exception as exc:
        log.warning("screensense explain failed: %s", exc)
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "error": "vision-unavailable",
                "message": "I took the screenshot, but I could not look at it just now.",
                "frame_id": inp.frame_id,
            },
        )

    # V3. `error_code` is what a retry ladder switches on; `message` is what a person reads.
    # A model that returned nothing is not "your computer failed" — the screenshot is fine and
    # still on screen, so the sentence says which half worked.
    code = result.get("error_code", "")
    message = ""
    if code == "empty_model_response":
        model = (result.get("meta") or {}).get("model") or "the vision model"
        message = f"I took the screenshot, but {model} did not give me anything readable about it."
    return JSONResponse(
        status_code=200,
        content={
            "ok": bool(result.get("ok")),
            "frame_id": inp.frame_id,
            "analysis_text": result.get("analysis_text", ""),
            "error": result.get("error", ""),
            "error_code": code,
            "message": message,
            "meta": result.get("meta", {}),
        },
    )


@router.delete("/v1/screensense/frame/{frame_id}")
async def forget(frame_id: str) -> JSONResponse:
    """Delete one frame now, before its TTL. The user's own "forget that" button."""
    return JSONResponse(status_code=200, content={"ok": True, "removed": frames.drop(frame_id)})


# ── the sharing tab's side of the conversation ─────────────────────────────


@router.get("/v1/screensense/agent/poll")
async def agent_poll(wait: float = Query(25.0, ge=0.5, le=60.0)) -> JSONResponse:
    """Long-poll for something to photograph. An empty answer is normal, not an error."""
    job = await broker.poll(wait)
    if job is None:
        return JSONResponse(status_code=200, content={"ok": True, "request": None})
    return JSONResponse(status_code=200, content={"ok": True, "request": job})


@router.post("/v1/screensense/agent/frame")
async def agent_frame(
    request_id: str = Form(...),
    file: UploadFile = File(...),
) -> JSONResponse:
    """The tab's answer to one poll. Rejected once the request it answers has timed out."""
    data = await file.read(MAX_FRAME_BYTES + 1)
    await file.close()
    if len(data) > MAX_FRAME_BYTES:
        return JSONResponse(status_code=413, content={"ok": False, "error": "frame-too-large"})
    if not data:
        return JSONResponse(status_code=400, content={"ok": False, "error": "empty-frame"})
    if not broker.deliver(request_id, data):
        # Not an error worth shouting about: the capture gave up and moved on, and the tab
        # has no way of knowing that until it tries.
        return JSONResponse(status_code=200, content={"ok": False, "error": "no-such-request"})
    return JSONResponse(status_code=200, content={"ok": True})
