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

from . import ask as ask_mod
from . import audio as audio_wire
from . import binding as binding_mod
from . import chips as chips_mod
from . import export as export_mod
from . import keyframes as keyframes_mod
from . import notes_engine as notes_engine_mod
from . import retention as retention_mod
from . import session as session_mod
from . import store
from .config import load_config

log = logging.getLogger(__name__)

#: The helper modes W9 will implement. Named here because a mode has to be *refused* now — one
#: nobody implements yet is still a mode, and a typo is not.
MODES = ("note-taker", "participant", "presenter", "coach", "practice")

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

    ``provider`` is named rather than merely counted because a remote endpoint is a different
    privacy answer from a local model, and the consent sheet has to be able to say which.
    Until LS2 it was also the *surprising* answer: the shared selection preferred a configured
    ``STT_BASE_URL`` over local Whisper, so somebody who set that months ago for voice calls
    had every hour of meeting audio shipped there without being told. Meetings now ask
    ``get_meeting_stt_provider()``, which starts from local and never crosses that boundary on
    its own; ``policy`` reports which rule is in force.
    """
    info: Dict[str, Any] = {
        "available": False,
        "provider": None,
        "segments": False,
        "remote": False,
        "device": None,
        "policy": "local",
        "offer_remote": False,
        "hint": "Install local speech (pip install -r requirements/speech-cpu.txt) to transcribe meetings on this computer.",
    }
    try:
        from ..voice.providers import get_meeting_stt_provider, meeting_stt_policy

        info["policy"] = meeting_stt_policy()
        provider = get_meeting_stt_provider()
        info["provider"] = getattr(provider, "name", None)
        info["available"] = bool(getattr(provider, "available", False))
        # Not "does the method exist" — MS1 put `transcribe_segments` on the base class so a
        # caller never has to branch, which means it exists everywhere and asking that
        # question would answer yes for a provider that only guesses. The real question is
        # whether the timings were *measured*, which is what `supports_segments` reports.
        info["segments"] = bool(getattr(provider, "supports_segments", False))
        # A remote provider is a legitimate choice, not an error — but the user should be
        # the one making it. LS2: this is now whether the meeting *is* using a remote
        # provider, not merely whether one is configured somewhere. Those were the same
        # question while a configured endpoint silently won, and are not any more.
        info["remote"] = getattr(provider, "name", "") == "openai-compat"
        info["remote_configured"] = bool(os.getenv("STT_BASE_URL", "").strip())
        # None until the model has loaded once — a different answer from "loaded on CPU",
        # and reported as such rather than flattened into a guess.
        info["device"] = getattr(provider, "device", None)
        requested = getattr(provider, "requested_device", None)
        if requested and info["device"] and requested != info["device"]:
            info["device_note"] = f"requested {requested}, running on {info['device']}"
        if info["available"]:
            info["hint"] = None
        elif info["remote_configured"] and info["policy"] == "local":
            # The one case where the honest answer is a question rather than an instruction.
            # Defaulting meetings to local is right, and silently taking away transcription
            # from somebody who was relying on their configured endpoint is not — so the UI
            # is told the offer exists and lets them make it.
            info["offer_remote"] = True
            info["hint"] = (
                "Local transcription isn't installed on this computer. You have a remote "
                "speech service configured — meetings won't use it unless you say so."
            )
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
        from ..voice.providers import get_meeting_stt_provider

        candidate = get_meeting_stt_provider()
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
        # MS9. Resolved once for the connection rather than per keyframe. None on an install
        # with no multimodal module: slides are then recorded with timestamps and no captions,
        # which is a complete meeting rather than a degraded one.
        vision=keyframes_mod.vision_bridge(cfg),
        # MS12-a. Built on `start` when the client asks for notes — the wiring MS12 shipped
        # without, which left `notes: true` echoed back over a meeting that produced none.
        notes_factory=notes_engine_mod.engine_factory(cfg),
        # MS26. Participant answers to its own name and drafts for the user's, and both go
        # through MS13's `answer` — the budget, the tiers and the citation rule were argued
        # once. Bound here rather than imported inside the session so a test injects a stub.
        ask=_ask_bridge(),
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

                elif kind == "ask":
                    # Answered on the socket the question arrived on, so a question asked
                    # mid-meeting does not need a second round trip through HTTP.
                    await _handle_ask(session, message)

                elif kind == "chip_action":
                    # MS25. The user said yes to a chip. The id is all that crosses the wire —
                    # see `_handle_chip_action`.
                    await _handle_chip_action(session, message)

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


@router.get("/v1/meetingsense/meetings")
async def list_meetings(limit: int = Query(25), conversation_id: str = Query("")) -> Dict[str, Any]:
    """Recent meetings, or the meetings in one conversation (MS21).

    Declared above ``/{meeting_id}`` for the same reason ``/conversations`` is: a path
    parameter first reads "meetings" as a meeting id and 404s.
    """
    if not load_config().enabled:
        return {"meetings": []}
    limit = max(1, min(int(limit or 25), 100))
    try:
        if conversation_id.strip():
            rows = store.meetings_for_conversation(conversation_id.strip())[-limit:]
        else:
            rows = store.list_meetings(limit=limit)
    except Exception:  # noqa: BLE001 — an install with no tables has no meetings
        return {"meetings": []}
    return {"meetings": rows}


@router.get("/v1/meetingsense/search")
async def search_meetings(
    q: str = Query(""), meeting_id: str = Query(""), k: int = Query(8)
) -> Dict[str, Any]:
    """MS15's retrieval, over HTTP (MS21).

    The same ``ms_search`` the MCP tool and a persona's `Recall` node call, rather than a
    second scorer behind an endpoint: one implementation, and every caller gets the citation
    with it.
    """
    if not load_config().enabled:
        return {"results": []}
    from . import retrieval as retrieval_mod

    rows = retrieval_mod.ms_search(q, meeting_id.strip() or None, max(1, min(int(k or 8), 25)))
    return {"results": rows}


@router.get("/v1/meetingsense/conversations/{conversation_id}/live")
async def live_context(conversation_id: str) -> Dict[str, Any]:
    """MS18's bounded block for whatever is recording in this conversation (MS21).

    The same block, not a bigger one: an endpoint that returned more than the prompt does
    would be a way around D9's budget.
    """
    from . import live_context as live_mod

    block = live_mod.for_conversation(conversation_id)
    return {"conversation_id": conversation_id, "live": bool(block), "block": block}


@router.get("/v1/meetingsense/conversations/{conversation_id}")
async def meetings_in_conversation(conversation_id: str) -> Dict[str, Any]:
    """The meetings a conversation can bring a card back for (MS16).

    Declared **above** ``/{meeting_id}``: FastAPI matches in declaration order, and a path
    parameter placed first would swallow "conversations" as a meeting id and 404 on every
    call. That is the kind of bug that looks like a missing feature.

    Never 404s. A conversation with no meetings in it is the normal case, and the chat load
    path asks this on every open — an error there would be a red toast on a chat that is fine.
    """
    empty = {"conversation_id": conversation_id, "meetings": []}
    # Gated like every other read, but *empty* rather than 404: turning the flag off leaves
    # the tables where they are, and a chat that used to host a meeting should stop showing
    # its card rather than start erroring.
    if not load_config().enabled:
        return empty
    try:
        return {"conversation_id": conversation_id, "meetings": binding_mod.hydrate(conversation_id)}
    except Exception:  # noqa: BLE001 — an install with no tables has no meetings
        return empty


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


@router.patch("/v1/meetingsense/{meeting_id}")
async def rename_meeting(meeting_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Set a meeting's own metadata — in practice, its title (MS33).

    MS17 gave a meeting a title from a calendar event or a shared window, and `UPDATABLE`
    has always allowed the columns a person might correct. Nothing could reach them: naming
    a meeting was a capability with no door.

    Renaming is safe and immediate — it changes a label, nothing else, and the previous
    title is one more rename away. So it takes no confirmation, unlike the delete below it
    in the same menu.

    `store.update_meeting` refuses anything outside `UPDATABLE` and refuses empty values, so
    a blank title cannot erase the one a calendar found. That is a store rule rather than a
    route rule on purpose: it holds for every caller.
    """
    _require_meeting(meeting_id)
    fields = {k: v for k, v in (body or {}).items() if k in store.UPDATABLE}
    if not fields:
        raise HTTPException(status_code=400, detail=f"one of {', '.join(store.UPDATABLE)} is required")
    written = store.update_meeting(meeting_id, fields)
    if not written:
        # Every field was empty. Nothing was written and nothing was destroyed; say so
        # rather than reporting a success the store did not perform.
        raise HTTPException(status_code=400, detail="no writable value given")
    return {"ok": True, "written": written, "meeting": store.get_meeting(meeting_id)}


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


@router.delete("/v1/meetingsense/{meeting_id}")
async def delete_meeting_route(meeting_id: str) -> Dict[str, Any]:
    """Delete a meeting: its rows, and the files it owned (MS14).

    One call, because deletion is the one thing a user must never have to do twice to be sure
    of. It reports counts rather than "ok": somebody deleting a meeting with twelve slides is
    entitled to know whether the twelve images went with it.

    Retention does not modify this. Whatever was kept is removed — a mode that let something
    survive an explicit delete would be a setting quietly overriding an instruction.
    """
    _require_meeting(meeting_id)

    # A live meeting is stopped first. Deleting the rows under a running session would leave it
    # transcribing into a meeting that no longer exists, and the next segment would resurrect a
    # row the user thought they had removed.
    session = session_mod.get(meeting_id)
    if session is not None:
        with contextlib.suppress(Exception):
            await session.stop()
        session_mod.unregister(meeting_id)

    result = retention_mod.delete_meeting(meeting_id)
    if result is None:
        raise HTTPException(status_code=404, detail="not found")
    return result


async def _handle_ask(session, message: Dict[str, Any]) -> Dict[str, Any]:
    """Answer a question about the meeting in progress (MS13).

    ``now_ms`` is the session's own elapsed time rather than the last segment's, because a
    question asked during a silence is still about *now* — using the last segment would slide
    the verbatim window backwards every time somebody stopped talking.
    """
    from .notes_engine import call_model

    frame = await ask_mod.answer(
        session.meeting_id,
        str(message.get("text") or ""),
        call=call_model,
        now_ms=session.elapsed_ms,
    )
    await session.transport.send(frame)
    return frame


def _ask_bridge():
    """MS13's `answer`, bound to the local model. ``None`` on an install with no model.

    Mirrors `keyframes.vision_bridge`: MeetingSense reads another subsystem's capability at the
    edge and the core holds no opinion about it. ``None`` means Participant offers no drafts
    and answers to no name, which is the correct behaviour for an install that cannot answer
    anything — not a degraded one.
    """
    from .notes_engine import call_model

    async def ask(meeting_id: str, question: str, *, mode: str = "") -> Dict[str, Any]:
        return await ask_mod.answer(meeting_id, question, call=call_model, mode=mode)

    return ask


async def _handle_chip_action(session, message: Dict[str, Any]) -> Dict[str, Any]:
    """Run the proposal on a chip the user accepted (MS25).

    **An id crosses the wire, never a chip.** The server offered the chip and the server still
    has it, so what runs is what was shown. Accepting a body instead would let whatever is on
    the page rewrite the arguments between the offer and the acceptance, and ask-before-acting
    would be asking about one thing and acting on another.

    An unknown id is answered rather than ignored: it means the card and the server disagree
    about what is on screen — a reconnect, a second client, a stale render — and a button that
    silently does nothing is the worst version of that.
    """
    chip_id = str((message or {}).get("id") or "").strip()
    chip = session.chips.get(chip_id)
    if chip is None:
        return await session.send_error("chip_unknown", f"no chip {chip_id!r} in this meeting")

    result = await chips_mod.accept(
        session.meeting_id, chip,
        router=chips_mod.router_bridge(),
        tool_source=session.project_id,
    )
    frame = {"type": "chip_result", "id": chip_id, **result}
    await session.transport.send(frame)
    return frame


@router.post("/v1/meetingsense/{meeting_id}/prep")
async def attach_prep(meeting_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Attach prep material for Coach (MS27).

    The only thing Coach draws talking points from. Stored as text on the meeting rather than
    as a pointer into a project, because a pointer is a restriction somebody else can widen.
    """
    _require_meeting(meeting_id)
    from .agent import coaching as coaching_mod

    added = coaching_mod.add_prep(meeting_id, str((body or {}).get("title") or ""),
                                  str((body or {}).get("text") or ""))
    if added is None:
        raise HTTPException(status_code=400, detail="text is required, and at most 10 documents")
    return {"meeting_id": meeting_id, "attached": added,
            "documents": [d["title"] for d in coaching_mod.prep(meeting_id)]}


@router.get("/v1/meetingsense/{meeting_id}/prep")
async def read_prep(meeting_id: str) -> Dict[str, Any]:
    """What Coach may draw on. Titles and sizes, not the bodies."""
    _require_meeting(meeting_id)
    from .agent import coaching as coaching_mod

    docs = coaching_mod.prep(meeting_id)
    return {"meeting_id": meeting_id,
            "documents": [{"title": d["title"], "words": len(d["text"].split())} for d in docs]}


@router.delete("/v1/meetingsense/{meeting_id}/prep")
async def clear_prep(meeting_id: str) -> Dict[str, Any]:
    """Take the prep material out. A real delete — it is the user's own document."""
    _require_meeting(meeting_id)
    from .agent import coaching as coaching_mod

    return {"meeting_id": meeting_id, "cleared": coaching_mod.drop_prep(meeting_id)}


@router.post("/v1/meetingsense/{meeting_id}/rehearsal")
async def set_rehearsal(meeting_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Set up a Practice rehearsal (MS27)."""
    _require_meeting(meeting_id)
    from .agent import practice as practice_mod

    brief = practice_mod.set_brief(meeting_id, kind=str((body or {}).get("kind") or ""),
                                   role=str((body or {}).get("role") or ""),
                                   notes=str((body or {}).get("notes") or ""))
    if brief is None:
        raise HTTPException(status_code=400,
                            detail=f"kind must be one of {', '.join(practice_mod.KINDS)}")
    return {"meeting_id": meeting_id, "rehearsal": brief}


@router.get("/v1/meetingsense/voice-out")
async def voice_out_capability(desktop: bool = False, devices: str = "",
                               system: str = "") -> Dict[str, Any]:
    """Can this install speak into a meeting, and if not, what to install (MS27).

    `devices` is a comma-separated list the desktop app enumerated. The backend has no audio
    stack and deliberately does not grow one: it recognises a device name, it does not go
    looking for one.
    """
    from .agent import voice_out as voice_mod

    names = [d.strip() for d in (devices or "").split(",") if d.strip()]
    return voice_mod.capability(desktop=desktop, devices=names, system=system or None)


@router.post("/v1/meetingsense/{meeting_id}/deck")
async def attach_deck(meeting_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Attach a deck to a meeting (MS26, Presenter).

    A list of `{"title": str, "minutes": number}`. Attached rather than inferred: pacing built
    on a guess is wrong the first time it matters, and the user turns the mode off.
    """
    _require_meeting(meeting_id)
    from .agent import presenter as presenter_mod

    sections = body.get("sections") if isinstance(body, dict) else None
    if not isinstance(sections, list) or not sections:
        raise HTTPException(status_code=400, detail="sections is required")
    stored = presenter_mod.set_deck(meeting_id, sections)
    if not stored:
        raise HTTPException(status_code=400, detail="no section had a title")
    return {"meeting_id": meeting_id, "sections": stored}


@router.get("/v1/meetingsense/{meeting_id}/deck")
async def read_deck(meeting_id: str) -> Dict[str, Any]:
    """The deck, and where the clock says it is."""
    _require_meeting(meeting_id)
    from .agent import presenter as presenter_mod

    sections = presenter_mod.deck(meeting_id)
    return {"meeting_id": meeting_id, "sections": sections,
            "planned_ms": presenter_mod.planned_ms(sections)}


@router.get("/v1/meetingsense/{meeting_id}/queue")
async def read_queue(meeting_id: str) -> Dict[str, Any]:
    """Audience questions waiting (MS26, Presenter). Oldest first."""
    _require_meeting(meeting_id)
    from .agent import presenter as presenter_mod

    return {"meeting_id": meeting_id, "questions": presenter_mod.queued(meeting_id)}


@router.post("/v1/meetingsense/{meeting_id}/queue")
async def resolve_queue(meeting_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Take a question off the queue, once the user has dealt with it."""
    _require_meeting(meeting_id)
    from .agent import presenter as presenter_mod

    text = str((body or {}).get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    cleared = presenter_mod.mark_answered(meeting_id, text)
    return {"meeting_id": meeting_id, "cleared": cleared,
            "questions": presenter_mod.queued(meeting_id)}


@router.post("/v1/meetingsense/{meeting_id}/ask")
async def ask_meeting(meeting_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Ask about a meeting that has ended.

    The same function the live socket uses, so an answer does not depend on whether the
    meeting is still running — only on how much of it exists.
    """
    _require_meeting(meeting_id)
    question = str((body or {}).get("text") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="text is required")

    from .notes_engine import call_model

    return await ask_mod.answer(meeting_id, question, call=call_model)


@router.post("/v1/meetingsense/{meeting_id}/notes")
async def amend_notes(meeting_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Amend a meeting's notes, or leave something beside them (MS21).

    Three operations, because they are three different kinds of statement and keeping them
    apart is what makes the meeting's own record citeable:

    * ``action`` closes or reopens an item **in** the notes — a claim about what the meeting
      decided, so it belongs with the rest of them.
    * ``suggestion`` is what an agent thinks, recorded as an artifact **beside** the notes.
      Merged in, it would be indistinguishable from something that was said.
    * ``mode`` records which helper mode was asked for. W9 owns what a mode does; this is so
      the request is not lost between waves.
    """
    _require_meeting(meeting_id)
    op = str((body or {}).get("op") or "").strip().lower()
    text = str((body or {}).get("text") or "").strip()

    if op == "action":
        if not text:
            raise HTTPException(status_code=400, detail="text is required")
        stored = export_mod.notes_body(store.get_notes(meeting_id)) or {}
        notes = dict(stored)
        actions = [dict(a) for a in (notes.get("actions") or [])]
        match = next((a for a in actions
                      if (a.get("text") or "").strip().lower() == text.lower()), None)
        if match is None:
            # Added rather than refused: an agent that has just done something the meeting
            # did not record has still done it.
            match = {"text": text}
            actions.append(match)
        match["done"] = bool(body.get("done", True))
        owner = str(body.get("owner") or "").strip()
        if owner:
            match["owner"] = owner
        notes["actions"] = actions
        return {"ok": True, "version": store.save_notes(meeting_id, notes), "actions": actions}

    if op == "suggestion":
        if not text:
            raise HTTPException(status_code=400, detail="text is required")
        artifact = store.add_artifact(meeting_id, kind="suggestion",
                                      target=str(body.get("kind") or "note"), ref=text)
        return {"ok": True, "artifact_id": artifact}

    if op == "mode":
        mode = str(body.get("mode") or "").strip().lower()
        if mode not in MODES:
            raise HTTPException(status_code=400,
                                detail=f"unknown mode; expected one of {', '.join(MODES)}")
        return {"ok": True, "mode": mode,
                "artifact_id": store.add_artifact(meeting_id, kind="mode", target=mode)}

    raise HTTPException(status_code=400, detail="op must be one of: action, suggestion, mode")


@router.post("/v1/meetingsense/{meeting_id}/thread")
async def branch_meeting(meeting_id: str, body: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Open a new conversation from a meeting, with a brief (MS16).

    Returns the conversation id the client should navigate to. The brief is written as an
    assistant message, so History labels the new thread with the meeting it came from even
    before anybody says anything in it.
    """
    _require_meeting(meeting_id)
    result = binding_mod.branch(meeting_id, conversation_id=(body or {}).get("conversation_id"))
    if result is None:
        raise HTTPException(status_code=404, detail="not found")
    return result


@router.post("/v1/meetingsense/{meeting_id}/attach")
async def attach_meeting(meeting_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Push a meeting's transcript into a project's knowledge base (MS16).

    A deliberate act, and the only route by which a meeting reaches project jobs (D4): being
    recorded does not put a meeting into a project, and this endpoint is somebody deciding it
    should be.
    """
    _require_meeting(meeting_id)
    project_id = str((body or {}).get("project_id") or "").strip()
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    result = binding_mod.attach_to_project(meeting_id, project_id)
    if result is None:
        raise HTTPException(status_code=404, detail="not found")
    return result


# ── MS29: the screen the user is sharing ────────────────────────────────────


@router.post("/v1/meetingsense/screen/{conversation_id}")
async def screen_share_state(conversation_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Tell the server a screen share started, stopped, or was looked at (MS29).

    Three verbs on one route because they are one fact — "a screen is being shared here" —
    changing state, and three routes would be three places to keep that fact consistent.

    Not gated on ``enabled``: this is the seam that makes a persona stop denying it can see the
    screen, and it is the one part of MeetingSense that stands alone. ScreenSense works on an
    install with the recorder switched off, and this has to work there too.
    """
    from . import screen_context as screen_mod

    action = str((body or {}).get("action") or "").strip().lower()
    if action == "start":
        ok = screen_mod.begin(conversation_id, mode=str((body or {}).get("mode") or "browser"))
    elif action == "stop":
        ok = screen_mod.end(conversation_id)
    elif action == "seen":
        ok = screen_mod.observe(conversation_id, str((body or {}).get("caption") or ""))
    else:
        raise HTTPException(status_code=400, detail="action must be start, stop or seen")
    return {"conversation_id": conversation_id, "action": action, "ok": ok,
            "sharing": screen_mod.active(conversation_id) is not None}
