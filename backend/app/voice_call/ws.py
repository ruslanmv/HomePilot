"""
WebSocket orchestrator for voice-call sessions.

Transport
---------
Path:            ``/v1/voice-call/ws/{session_id}``
Query param:     ``resume_token=<token issued at POST /sessions>``
                 (headers don't round-trip cleanly from browsers; a
                 short-lived query token is the standard WS-auth trick)

Protocol
--------
Server and client exchange JSON envelopes::

    { "type": "<event>", "seq": <int?>, "ts": <ms>, "payload": { ... } }

Client → server (each is harmless if the server can't handle it —
forward-compatible by design):
    ui.state            { muted, speaker_on, backgrounded }
    transcript.final    { text, lang? }
    call.control        { action: "end" | "ping" }

Server → client:
    call.state          { status, since }
    transcript.final    { role: "assistant", text }
    error               { code, message }
    pong                { ts }
    safety.notice       (forwarded from upstream providers, reserved)

Out of scope for MVP (per review): transcript.partial (requires chat
endpoint streaming, which returns 501 today), raw audio frames, server-
side barge-in.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect, status

from . import service, store, turn
from .config import VoiceCallConfig


logger = logging.getLogger("voice_call.ws")

HEARTBEAT_INTERVAL_SEC = 10.0


def _now_ms() -> int:
    return int(time.time() * 1000)


async def _send(ws: WebSocket, type_: str, payload: Dict[str, Any], *,
                session_id: str) -> None:
    """Send a server→client event with a monotonic seq number."""
    seq = service._next_event_seq(session_id)
    env = {"type": type_, "seq": seq, "ts": _now_ms(), "payload": payload}
    try:
        await ws.send_text(json.dumps(env, separators=(",", ":")))
    except Exception:
        # WebSocket already closed; caller will clean up.
        raise
    # Only persist the *type* for privacy unless the user has explicitly
    # opted into transcript storage.
    store.append_event(
        session_id=session_id, seq=seq, event_type=type_,
        payload={},  # intentionally empty
    )


async def _send_error(ws: WebSocket, session_id: str, code: str, msg: str) -> None:
    try:
        await _send(ws, "error",
                    {"code": code, "message": msg},
                    session_id=session_id)
    except Exception:
        pass  # best-effort


async def _resolve_session_for_ws(
    ws: WebSocket, session_id: str, resume_token: Optional[str],
    cfg: VoiceCallConfig,
) -> Optional[Dict[str, Any]]:
    """Validate the handshake. Closes the socket with a clean code if
    anything is off."""
    if not cfg.websocket_enabled:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION,
                       reason="websocket-disabled")
        return None
    row = store._select_session(session_id)
    if row is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION,
                       reason="session-not-found")
        return None
    if not resume_token or row.get("resume_token") != resume_token:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION,
                       reason="bad-resume-token")
        return None
    if row.get("status") == "ended":
        await ws.close(code=status.WS_1008_POLICY_VIOLATION,
                       reason="session-ended")
        return None
    # Resume window: an "interrupted" session is only acceptable if the
    # drop happened within the configured window.
    if row.get("status") == "interrupted":
        last_update = int(row.get("updated_at") or 0)
        if _now_ms() - last_update > cfg.resume_window_sec * 1000:
            service.mark_ended_by_timeout(session_id, "resume_expired")
            await ws.close(code=status.WS_1008_POLICY_VIOLATION,
                           reason="resume-expired")
            return None
    return row


async def run_session_ws(
    ws: WebSocket,
    session_id: str,
    resume_token: Optional[str],
    cfg: VoiceCallConfig,
) -> None:
    """Main WS loop for one session. Called from router after
    ``await ws.accept()``.

    Ownership is established by the resume token alone (token is only
    ever handed to the user who created the session). The per-turn
    chat request also carries the caller's bearer — so the chat
    endpoint does its own auth and refuses foreign personas even if
    the token somehow leaks."""
    session = await _resolve_session_for_ws(ws, session_id, resume_token, cfg)
    if session is None:
        return  # close already issued

    # Extract the bearer from the WS query so turn.py can re-use it.
    # Browsers can't attach custom headers to WS; the client passes
    # ?token=<jwt> alongside ?resume_token=.
    query_bearer = ws.query_params.get("token") or None

    sid = session["id"]
    service.mark_live(sid)
    await _send(ws, "call.state", {"status": "live"}, session_id=sid)

    # Heartbeat keeps idle TCP paths alive on mobile networks.
    hb_task = asyncio.create_task(_heartbeat_loop(ws, sid, cfg))

    try:
        while True:
            try:
                text = await asyncio.wait_for(
                    ws.receive_text(),
                    timeout=cfg.idle_timeout_sec,
                )
            except asyncio.TimeoutError:
                await _send_error(ws, sid, "idle_timeout",
                                  "No activity for a while — ending call.")
                service.end_session(sid=sid, user_id=session["user_id"],
                                    reason="idle")
                await _send(ws, "call.state", {"status": "ended",
                                               "reason": "idle"},
                            session_id=sid)
                break

            try:
                env = json.loads(text)
            except json.JSONDecodeError:
                await _send_error(ws, sid, "bad_json", "Invalid JSON envelope.")
                continue

            evt_type = env.get("type")
            payload = env.get("payload") or {}

            if evt_type == "call.control":
                action = (payload.get("action") or "").strip()
                if action == "end":
                    service.end_session(sid=sid, user_id=session["user_id"],
                                        reason="user_ended")
                    await _send(ws, "call.state", {"status": "ended",
                                                   "reason": "user_ended"},
                                session_id=sid)
                    break
                if action == "ping":
                    await _send(ws, "pong", {}, session_id=sid)

            elif evt_type == "ui.state":
                # Pure bookkeeping. Client tells us muted / speaker_on /
                # backgrounded; we persist only the type (privacy).
                pass

            elif evt_type == "transcript.final":
                text_in = (payload.get("text") or "").strip()
                if not text_in:
                    continue
                model = (
                    payload.get("model")
                    or session.get("persona_id")
                    and f"persona:{session['persona_id']}"
                    or "llama3:8b"
                )

                # ── persona_call hook ───────────────────────────────
                # Additive, behind its own feature flag. Composes a
                # per-turn system SUFFIX (never touches the persona's
                # base system prompt) and — if cfg.apply is True —
                # appends it as an extra system message on the chat
                # call. Wraps the turn in a filler scheduler so a long
                # LLM wait produces a "hmm…" event within 600 ms.
                pc_additional_system: Optional[str] = None
                pc_persona_id: Optional[str] = session.get("persona_id")
                try:
                    from ..persona_call import (
                        config as _pc_cfg_mod,
                        context as _pc_context,
                        directive as _pc_directive,
                        facets as _pc_facets,
                        latency as _pc_latency,
                    )
                    _pc_cfg = _pc_cfg_mod.load()
                except Exception:
                    _pc_cfg = None  # persona_call not importable; skip

                _pc_facets_obj = None
                if _pc_cfg is not None and _pc_cfg.enabled:
                    try:
                        _pc_env = _pc_context.compute_env(
                            tz=(session.get("client_platform") and None),
                            weeks_since_last_call=-1,
                        )
                        _pc_facets_obj = _pc_facets.for_persona_id(pc_persona_id)
                        composed = _pc_directive.compose(
                            session_id=sid,
                            persona_id=pc_persona_id,
                            user_text=text_in,
                            env=_pc_env,
                            cfg=_pc_cfg,
                            facets=_pc_facets_obj,
                        )
                        if _pc_cfg.apply and composed.system_suffix:
                            pc_additional_system = composed.system_suffix
                    except Exception as _pc_err:
                        # Shadow fail — turn still runs without the
                        # phone-call suffix. persona_call must never
                        # break an otherwise-working call.
                        logger.warning(
                            "[persona_call] compose skipped: %s", _pc_err
                        )

                async def _pc_send(env_: dict) -> None:
                    try:
                        await ws.send_text(
                            json.dumps(env_, separators=(",", ":"))
                        )
                    except Exception:
                        pass

                try:
                    if _pc_cfg is not None and _pc_cfg.enabled and _pc_facets_obj is not None:
                        async with _pc_latency.FillerScheduler(
                            send=_pc_send,
                            facets=_pc_facets_obj,
                            cfg=_pc_cfg,
                            session_id=sid,
                        ):
                            assistant_text = await turn.run_turn(
                                user_text=text_in,
                                model=model,
                                auth_bearer=query_bearer,
                                additional_system=pc_additional_system,
                            )
                    else:
                        assistant_text = await turn.run_turn(
                            user_text=text_in,
                            model=model,
                            auth_bearer=query_bearer,
                            additional_system=pc_additional_system,
                        )
                except Exception as exc:
                    logger.warning("[voice_call] turn failed: %s", exc)
                    await _send_error(ws, sid, "turn_failed", str(exc)[:400])
                    continue

                await _send(ws, "transcript.final",
                            {"role": "assistant", "text": assistant_text},
                            session_id=sid)

                # Record the reply into the anti-repetition ledger so
                # the NEXT turn can forbid the just-used opener/ack.
                if _pc_cfg is not None and _pc_cfg.enabled:
                    try:
                        _pc_directive.record_persona_reply(
                            session_id=sid,
                            persona_id=pc_persona_id,
                            reply=assistant_text,
                            cfg=_pc_cfg,
                        )
                    except Exception as _pc_err:
                        logger.warning(
                            "[persona_call] record_reply skipped: %s",
                            _pc_err,
                        )

            else:
                # Forward-compat: unknown event type is a no-op, not an
                # error. Older servers + newer clients stay friendly.
                pass
    except WebSocketDisconnect:
        # Client dropped — park the session as 'interrupted' so a resume
        # request within the window can pick it back up.
        service.mark_interrupted(sid)
    except Exception as exc:
        logger.exception("[voice_call] ws error for %s: %s", sid, exc)
        try:
            await _send_error(ws, sid, "internal", "Internal error")
        except Exception:
            pass
        service.mark_interrupted(sid)
    finally:
        hb_task.cancel()
        try:
            await hb_task
        except Exception:
            pass


async def _heartbeat_loop(ws: WebSocket, session_id: str, cfg: VoiceCallConfig) -> None:
    """Send a server-initiated ping every N seconds. Doubles as a
    liveness check + hard-duration-cap enforcement."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
        row = store._select_session(session_id)
        if row is None or row["status"] == "ended":
            return
        # Enforce hard cap.
        started = int(row.get("started_at") or 0)
        if started and (_now_ms() - started) >= cfg.max_duration_sec * 1000:
            try:
                await _send(ws, "call.state",
                            {"status": "ending", "reason": "max_duration"},
                            session_id=session_id)
            except Exception:
                return
            service.end_session(sid=session_id, user_id=row["user_id"],
                                reason="max_duration")
            try:
                await ws.close(code=status.WS_1000_NORMAL_CLOSURE,
                               reason="max-duration")
            except Exception:
                pass
            return
        try:
            await _send(ws, "ping", {}, session_id=session_id)
        except Exception:
            return
