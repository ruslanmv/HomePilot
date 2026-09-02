"""MeetingSense HTTP routes (batch MS0).

Today this is one endpoint: ``GET /v1/meetingsense/status``. The session WebSocket arrives
in MS3, the per-meeting reads in MS6.

**Status answers even when MeetingSense is off, and that is the point.** A frontend needs to
know three different things apart: the feature is disabled, the feature is enabled but this
machine cannot transcribe, and the feature is ready. One 404 collapses all three into "no",
and the user is left guessing which. So the route is always mounted, always answers 200, and
reports capabilities honestly whichever way the flag is set — which is also what lets the
Settings panel say *"Set WHISPER_MODEL=small to enable"* instead of greying a control out
with no explanation, the way ``/v1/multimodal/analyze`` already names a missing vision model.

The capability probe never raises. A status endpoint that 500s because an optional package is
missing has failed at the one job it has: reporting what is missing.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import APIRouter

from .config import load_config

router = APIRouter(tags=["meetingsense"])


def stt_capability() -> Dict[str, Any]:
    """What this machine can do about speech, as three separate answers.

    ``available`` is whether anything can transcribe at all. ``segments`` is whether it can
    return *timed* spans — MS1 adds ``transcribe_segments`` to the provider layer, and until
    it lands this is false everywhere, which is the honest answer: the design cites
    timestamps that nothing currently produces.

    ``provider`` is named rather than merely counted because ``get_stt_provider()`` prefers
    the OpenAI-compatible endpoint whenever ``STT_BASE_URL`` is set. Someone who configured
    that months ago for voice calls would otherwise ship an hour of meeting audio to it
    without being told. Naming it here is what lets the consent sheet name it too.
    """
    info: Dict[str, Any] = {
        "available": False,
        "provider": None,
        "segments": False,
        "remote": False,
        "hint": "Set WHISPER_MODEL (e.g. small) for local transcription, or STT_BASE_URL for a remote one.",
    }
    try:
        from ..voice.providers import get_stt_provider

        provider = get_stt_provider()
        info["provider"] = getattr(provider, "name", None)
        info["available"] = bool(getattr(provider, "available", False))
        # MS1 adds this method beside the existing `transcribe`. Probing for it rather than
        # for a version keeps this line true before and after that batch, with no edit.
        info["segments"] = callable(getattr(provider, "transcribe_segments", None))
        # A remote provider is a legitimate choice, not an error — but the user should be
        # the one making it, so it is surfaced rather than assumed.
        info["remote"] = bool(os.getenv("STT_BASE_URL", "").strip())
        if info["available"]:
            info["hint"] = None
    except Exception as exc:  # noqa: BLE001 — every failure here is "cannot transcribe"
        info["hint"] = f"Speech providers unavailable: {exc}"
    return info


def vision_capability(configured_model: str) -> Dict[str, Any]:
    """Whether slides can be captioned, and by which model.

    Vision is not required for a meeting — the recorder works without it and the slide strip
    simply stays empty — so this reports a capability, never a blocker.
    """
    info: Dict[str, Any] = {
        "available": False,
        "model": None,
        "hint": "Set MEETINGSENSE_VISION_MODEL or a default multimodal model to caption slides.",
    }
    try:
        model = configured_model or os.getenv("MULTIMODAL_MODEL", "").strip()
        if model:
            info["model"] = model
            info["available"] = True
            info["hint"] = None
    except Exception as exc:  # noqa: BLE001
        info["hint"] = f"Vision unavailable: {exc}"
    return info


def _probe(fn, label: str) -> Dict[str, Any]:
    """Run a capability probe, turning any failure into a reported unknown."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — the whole point is that nothing escapes
        return {"available": False, "hint": f"{label} probe failed: {exc}"}


@router.get("/v1/meetingsense/status")
async def meetingsense_status() -> Dict[str, Any]:
    """Report whether MeetingSense can run here, and if not, what is missing.

    Deliberately unauthenticated and side-effect free, like ``/health``: it reveals no
    meeting content, only whether the feature exists on this install. The frontend calls it
    to decide whether to show the entry point at all, so a stale build cannot offer a control
    the backend would refuse.
    """
    cfg = load_config()
    # The probes catch their own errors — and the guarantee must not depend on every future
    # probe remembering to. A status endpoint that 500s because an optional package moved
    # has failed at the one job it has, so the failure is caught here too and reported as
    # the capability being unknown.
    stt = _probe(stt_capability, "speech")
    vision = _probe(lambda: vision_capability(cfg.vision.model), "vision")

    # "Ready" is a stricter question than "enabled": the flag is the operator's intent, and
    # this is whether the machine can honour it. The UI needs both — one to decide whether to
    # show the control, the other to decide whether it works.
    ready = bool(cfg.enabled and stt["available"])

    return {
        "enabled": cfg.enabled,
        "ready": ready,
        "retention": cfg.retention,
        "flags": cfg.flags.as_dict(),
        "stt": stt,
        "vision": vision,
        # Echoed so a client can lay out a card without a second call, and so a mismatch
        # between the two sides shows up as a number rather than a rendering bug.
        "limits": {
            "panel_max_kb": cfg.panels.max_kb,
            "max_keyframes_per_hour": cfg.vision.max_keyframes_per_hour,
        },
    }
