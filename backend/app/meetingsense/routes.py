"""MeetingSense HTTP routes (batches MS0, MS3).

``GET /v1/meetingsense/status`` and ``WS /v1/meetingsense/session``. The per-meeting reads
arrive in MS6.

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

import asyncio
import contextlib
import logging
import os
import time
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from . import audio as audio_wire
from . import export as export_mod
from . import session as session_mod
from . import store
from .config import load_config

log = logging.getLogger(__name__)

router = APIRouter(tags=["meetingsense"])


def stt_capability() -> Dict[str, Any]:
    """What this machine can do about speech, as three separate answers.

    ``available`` is whether anything can transcribe at all. ``segments`` is whether the
    timings are *measured* rather than assumed: every provider can return spans since MS1,
    but only one reads them off the model. A UI that cites a timestamp should know which it
    is looking at.

    ``device`` is the device the model actually loaded on, which is not always the one that
    was asked for — ``auto`` falls back to CPU silently when CUDA is present but unusable,
    and that silence is how someone concludes the latency budget is unachievable.

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
        "device": None,
        "hint": "Set WHISPER_MODEL (e.g. small) for local transcription, or STT_BASE_URL for a remote one.",
    }
    try:
        from ..voice.providers import get_stt_provider

        provider = get_stt_provider()
        info["provider"] = getattr(provider, "name", None)
        info["available"] = bool(getattr(provider, "available", False))
        # Not "does the method exist" — MS1 put `transcribe_segments` on the base class so a
        # caller never has to branch, which means it exists everywhere and asking that
        # question would answer yes for a provider that only guesses. The real question is
        # whether the timings were *measured*, which is what `supports_segments` reports.
        info["segments"] = bool(getattr(provider, "supports_segments", False))
        # A remote provider is a legitimate choice, not an error — but the user should be
        # the one making it, so it is surfaced rather than assumed.
        info["remote"] = bool(os.getenv("STT_BASE_URL", "").strip())
        # None until the model has loaded once — a different answer from "loaded on CPU",
        # and reported as such rather than flattened into a guess.
        info["device"] = getattr(provider, "device", None)
        requested = getattr(provider, "requested_device", None)
        if requested and info["device"] and requested != info["device"]:
            info["device_note"] = f"requested {requested}, running on {info['device']}"
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

    # MS8. Whether a meeting may arrive over the avatar session — the path a hosted page uses,
    # which cannot reach this endpoint directly and asks through whatever proxied it. Reported
    # as one boolean rather than leaving a client to infer it from two flags, because the two
    # deliberately do not imply each other: wanting meetings on your own machine is not
    # agreeing to accept them from somewhere else.
    remote_ok = bool(ready and cfg.flags.remote)

    return {
        "enabled": cfg.enabled,
        "ready": ready,
        "retention": cfg.retention,
        "flags": cfg.flags.as_dict(),
        "stt": stt,
        "vision": vision,
        "remote_ok": remote_ok,
        # Echoed so a client can lay out a card without a second call, and so a mismatch
        # between the two sides shows up as a number rather than a rendering bug.
        "limits": {
            "panel_max_kb": cfg.panels.max_kb,
            "max_keyframes_per_hour": cfg.vision.max_keyframes_per_hour,
        },
    }


# ── WS /v1/meetingsense/session (MS3) ───────────────────────────────────────


class WebSocketTransport:
    """MS2's :class:`~.session.Transport`, over a FastAPI WebSocket.

    The whole implementation is two forwarding methods, which is the point: MS2's core was
    written against this protocol precisely so the second transport (MS7, over the avatar
    session OllaBridge proxies) is another two methods rather than a second copy of the core.
    """

    def __init__(self, websocket: WebSocket) -> None:
        self._ws = websocket

    async def send(self, frame: Dict[str, Any]) -> None:
        await self._ws.send_json(frame)

    async def close(self) -> None:
        await self._ws.close()


def _stt_bridge(provider):
    """Adapt an STT provider to the callable :class:`~.session.MeetingSession` wants.

    One provider is held for the whole connection, the way ``voice/routes.py`` holds one:
    the model lives on the instance, so fetching a provider per utterance reloads it. MS1's
    cache makes a second fetch cheap rather than catastrophic, and this makes it unnecessary.
    """

    async def transcribe(data: bytes, *, fmt: str = "wav", duration_s=None):
        return await provider.transcribe_segments(data, fmt=fmt, duration_s=duration_s)

    return transcribe


async def _handle_audio(session, message: Dict[str, Any], channels: int) -> None:
    """Split one wire frame into per-speaker tracks and push each through the session.

    A stereo frame is two people, so it is two transcriptions. Deciding that here rather than
    inside the session keeps the core free of the wire format, which is the one thing it must
    not learn.
    """
    tracks = audio_wire.tracks(message, declared_channels=channels)
    partial = bool(message.get("partial"))
    for track in tracks:
        frame = {
            **message,
            "audio_bytes": track.wav,
            "format": "wav",
            # A mono recording cannot say who is talking, so the frame's own claim stands.
            "speaker": track.speaker or message.get("speaker"),
        }
        if partial:
            await session.on_partial(frame)
        else:
            await session.on_audio(frame)


@router.websocket("/v1/meetingsense/session")
async def meetingsense_session(websocket: WebSocket) -> None:
    """Record one meeting.

    Refuses when the flag is off exactly the way ``/v1/voice/session`` does — accept, say why,
    close 1008 — rather than rejecting the handshake. A client that gets a bare connection
    failure cannot tell "disabled" from "wrong URL" from "server down", and the popover would
    have nothing to explain to the user.

    Unknown frame types are ignored in both directions, the same rule the voice-call envelopes
    follow: a newer client talking to an older server should lose the feature it asked for,
    not the meeting it is recording.
    """
    await websocket.accept()
    cfg = load_config()

    if not cfg.enabled:
        await websocket.send_json(
            {"type": "error", "code": "disabled", "msg": "MeetingSense is disabled on this server"}
        )
        await websocket.close(code=1008)
        return

    # Tables are created on the first connection rather than at import, so an install that
    # never turns the flag on never grows them. `CREATE TABLE IF NOT EXISTS`, so the second
    # connection costs a no-op.
    try:
        store.migrate_if_enabled(cfg)
    except Exception as exc:  # noqa: BLE001 — a broken store is the one thing that is fatal
        await websocket.send_json({"type": "error", "code": "store_unavailable", "msg": str(exc)})
        await websocket.close(code=1011)
        return

    provider = None
    try:
        from ..voice.providers import get_stt_provider

        candidate = get_stt_provider()
        if getattr(candidate, "available", False):
            provider = candidate
    except Exception as exc:  # noqa: BLE001
        log.warning("meetingsense: no speech provider (%s)", exc)

    # A resume attaches this socket to a session that already exists, so the one built here
    # is only used if the client starts a new meeting. Building it up front keeps the frame
    # loop's error handling in one shape.
    session = session_mod.MeetingSession(
        transport=WebSocketTransport(websocket),
        config=cfg,
        # None when nothing can transcribe. The session then reports `stt: false` in `ready`
        # and refuses audio with a code — a meeting that records slides and markers without a
        # transcript is still a meeting, and is a better answer than refusing the connection.
        transcribe=_stt_bridge(provider) if provider is not None else None,
    )
    channels = 1

    try:
        while True:
            message = await websocket.receive_json()
            kind = (message or {}).get("type")

            try:
                if kind == "start":
                    declared = message.get("audio")
                    if isinstance(declared, dict):
                        channels = int(declared.get("channels") or 1)
                    await session.start(message)
                    session_mod.register(session)

                elif kind == "audio":
                    await _handle_audio(session, message, channels)

                elif kind == "keyframe":
                    await session.on_keyframe(message)

                elif kind == "mute":
                    await session.on_mute(message)

                elif kind == "resume":
                    resumed = await _handle_resume(websocket, session, message, cfg)
                    if resumed is not None:
                        session = resumed
                        channels = session.audio_channels or channels

                elif kind == "status":
                    await session.send_status(grace_s=cfg.resume.grace_s)

                elif kind == "stop":
                    await session.stop()
                    session_mod.unregister(session.meeting_id)
                    break

                elif kind == "ping":
                    await websocket.send_json({"type": "pong"})

                # Anything else is ignored on purpose — `marker` and `ask` belong to waves
                # that are not built, and a client sending them early should not be hung up
                # on mid-meeting.

            except audio_wire.AudioFrameError as exc:
                await session.send_error(exc.code, exc.detail)
            except session_mod.MeetingSessionError as exc:
                await session.send_error(exc.code, exc.detail)
            except Exception as exc:  # noqa: BLE001
                # One bad frame must not end a recording in progress. The socket stays up and
                # the client is told which frame failed.
                log.exception("meetingsense: %s frame failed", kind)
                await session.send_error("frame_failed", f"{kind} failed: {exc}")

    except WebSocketDisconnect:
        pass
    finally:
        await _on_disconnect(session, cfg)


async def _handle_resume(websocket: WebSocket, current, message: Dict[str, Any], cfg):
    """Re-attach this socket to a meeting that was dropped, per D10.

    Returns the session to carry on with, or ``None`` when the resume was refused — refused
    with an error frame and an open socket, never a close, because a client that reconnected
    only to be hung up on has no way to tell "too late" from "wrong server" and will keep
    trying.
    """
    meeting_id = str(message.get("meeting_id") or "").strip()
    if not meeting_id:
        await current.send_error("meeting_required", "resume needs a meeting_id")
        return None

    existing = session_mod.get(meeting_id)
    if existing is None or existing.state != session_mod.MeetingState.SUSPENDED:
        # Either the grace window closed, the process restarted, or the id is wrong. All three
        # mean the same thing to a client: this meeting cannot be continued, start a new one.
        await current.send_error("not_resumable", "that meeting is not resumable")
        return None

    try:
        await existing.resume(
            WebSocketTransport(websocket),
            last_seq=int(message.get("last_seq") or 0),
            max_replay=cfg.resume.max_replay,
        )
    except session_mod.MeetingSessionError as exc:
        await current.send_error(exc.code, exc.detail)
        return None
    return existing


async def _on_disconnect(session, cfg) -> None:
    """The socket died. Suspend rather than end, and arm the timer that ends it (D10).

    MS3 ended the meeting here, which is right for the store — no row saying "in progress"
    forever — and wrong for a person whose Wi-Fi blinked in the middle of a board meeting. A
    grace of zero restores MS3's behaviour exactly, and is the honest setting for anyone who
    would rather a drop be final.
    """
    if session.state != session_mod.MeetingState.LIVE:
        session_mod.unregister(session.meeting_id)
        return

    if cfg.resume.grace_s <= 0:
        try:
            await session.stop()
        except Exception:  # noqa: BLE001 — the socket is already gone
            log.debug("meetingsense: could not send the final frame", exc_info=True)
        session_mod.unregister(session.meeting_id)
        return

    session.suspend()
    session.expiry_task = asyncio.create_task(_expire_later(session, cfg.resume.grace_s))


async def _expire_later(session, grace_s: float) -> None:
    """Wait out the grace window, then end the meeting if nobody came back.

    Held on the session so a resume can cancel it — and so a test can await it rather than
    sleep for two minutes hoping.
    """
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.sleep(grace_s)
        try:
            await session_mod.expire_if_due(session, grace_s=grace_s, now=time.time())
        except Exception:  # noqa: BLE001 — a timer must not take the process down
            log.exception("meetingsense: could not expire meeting %s", session.meeting_id)


# ── reading a meeting back (MS6) ────────────────────────────────────────────


def _require_meeting(meeting_id: str) -> Dict[str, Any]:
    """Load a meeting, or refuse in a way a client can act on.

    404 for both "no such meeting" and "MeetingSense is off", deliberately: the status
    endpoint is where a client asks whether the feature exists, and answering that question
    again from every read would let a caller distinguish a real meeting id from a fabricated
    one on an install that never enabled the feature.
    """
    cfg = load_config()
    if not cfg.enabled:
        raise HTTPException(status_code=404, detail="not found")
    try:
        meeting = store.get_meeting(meeting_id)
    except Exception:  # noqa: BLE001 — an install with no tables has no meetings
        raise HTTPException(status_code=404, detail="not found") from None
    if meeting is None:
        raise HTTPException(status_code=404, detail="not found")
    return meeting


@router.get("/v1/meetingsense/{meeting_id}")
async def get_meeting(meeting_id: str) -> Dict[str, Any]:
    """Everything the card needs to rebuild itself.

    The card hydrates from this rather than replaying the socket, which is what lets a meeting
    be reopened days later, and what makes a reload during a live meeting cheap.
    """
    meeting = _require_meeting(meeting_id)
    return {
        "meeting": meeting,
        "segments": store.get_segments(meeting_id),
        "keyframes": store.get_keyframes(meeting_id),
        "notes": store.get_notes(meeting_id),
        # A live meeting is one with a socket attached right now, which the store cannot know.
        "live": session_mod.get(meeting_id) is not None
        and session_mod.get(meeting_id).state == session_mod.MeetingState.LIVE,
    }


@router.get("/v1/meetingsense/{meeting_id}/export")
async def export_meeting(meeting_id: str, fmt: str = Query("md")) -> Response:
    """Markdown to paste, SRT to lay over a recording, JSON for anything else."""
    fmt = (fmt or "md").strip().lower()
    if fmt not in export_mod.FORMATS:
        raise HTTPException(status_code=400, detail=f"format must be one of {', '.join(export_mod.FORMATS)}")

    meeting = _require_meeting(meeting_id)
    segments = store.get_segments(meeting_id)
    keyframes = store.get_keyframes(meeting_id)
    notes = store.get_notes(meeting_id)
    media_type, _ = export_mod.MEDIA_TYPES[fmt]
    # Named so a download lands in Downloads as something findable rather than as the id.
    disposition = f'attachment; filename="{export_mod.filename(meeting, fmt)}"'

    if fmt == "json":
        return JSONResponse(
            export_mod.to_json(meeting, segments, keyframes, notes),
            headers={"Content-Disposition": disposition},
        )
    body = (
        export_mod.to_srt(segments)
        if fmt == "srt"
        else export_mod.to_markdown(meeting, segments, keyframes, notes)
    )
    return Response(content=body, media_type=media_type, headers={"Content-Disposition": disposition})
