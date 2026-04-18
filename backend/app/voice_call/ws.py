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
import uuid
from typing import Any, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect, status

from . import barge_in as _barge_in
from . import service, store, turn, turn_stream
from .config import VoiceCallConfig


logger = logging.getLogger("voice_call.ws")


def _clog(event: str, **kwargs: Any) -> None:
    """Structured ``[call]`` log line — mirrors the frontend's clog()
    format so a single grep surfaces the whole round-trip. One
    ``logger.info`` per inflection point; fields stay flat so
    downstream log-shippers don't have to deserialize.

    Used at: session accept (open), call.state live (ready), opener
    greeting (greet), user transcript in (turn_user_in), assistant
    reply out (turn_assistant_out), cooperative cancel (barge_in),
    user-ended (hangup), WS teardown (close)."""
    logger.info("[call] %s %s", event, json.dumps(kwargs, separators=(",", ":"), default=str))

HEARTBEAT_INTERVAL_SEC = 10.0

# Protocol sentinels — reserved strings the frontend may send as a
# ``transcript.final`` payload to nudge backend state without asking
# the LLM to react. We drop these on the floor before the turn runner
# sees them; otherwise the model treats them as literal user speech
# and produces a confused reply (the classic "I'm not sure what
# [phone-call-open] means" double-greet). Add new sentinels here only
# when both sides have landed.
_PROTOCOL_SENTINELS = frozenset({
    "[phone-call-open]",
    "[phone-call-close]",
})


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
    _clog("lifecycle_open", sid=sid, persona_id=session.get("persona_id"))
    service.mark_live(sid)
    await _send(ws, "call.state", {"status": "live"}, session_id=sid)
    _clog("lifecycle_ready", sid=sid)

    # ── "Theory of answering" hook ────────────────────────────────
    # When persona_call is on, the persona answers first — the way a
    # real callee picks up the phone — instead of sitting silent
    # until the caller speaks. The opening text comes from the
    # curated bank in persona_call/openings.py; selection is
    # deterministic (seeded by session_id) + persona-aware + rotated
    # against the anti-repetition ledger, so the same caller never
    # hears the same greeting twice in a row.
    try:
        from ..persona_call import (
            config as _pc_cfg_mod,
            context as _pc_context,
            facets as _pc_facets,
            openings as _pc_openings,
            store as _pc_store,
        )
        _pc_cfg = _pc_cfg_mod.load()
        if _pc_cfg.enabled:
            _pc_store.ensure_schema()
            _pc_store.ensure_state(sid)
            _state = _pc_store.get_state(sid) or {}
            forbidden = list(_state.get("recent_openers") or [])
            _pc_env = _pc_context.compute_env(tz=None, weeks_since_last_call=-1)
            _pc_facets_obj = _pc_facets.for_persona_id(session.get("persona_id"))
            # We need the template *id* too so we can push it into
            # the ledger, so call choose() (not render() directly).
            tpl = _pc_openings.choose(
                _pc_facets_obj, _pc_env,
                session_id=sid,
                turn_index=1,
                forbidden_ids=forbidden,
            )
            greeting_text = None
            if tpl is not None:
                greeting_text = _pc_openings._interpolate(
                    tpl.text,
                    # Fall back to "Assistant" only if the session row
                    # has no persona_id — matches the frontend label.
                    (session.get("persona_id") or "Assistant").replace("persona:", "").strip(),
                )
                # Append the chosen id to the opener ledger, keeping
                # only the last N so the ledger doesn't grow
                # unbounded across long-lived sessions.
                window = max(1, _pc_cfg.opener_ledger_window)
                new_openers = (list(forbidden) + [tpl.id])[-window:]
                _pc_store.update_state(sid, recent_openers=new_openers)
            if greeting_text:
                await _send(ws, "transcript.final",
                            {"role": "assistant", "text": greeting_text},
                            session_id=sid)
                _clog("lifecycle_greet", sid=sid, text_len=len(greeting_text))
    except Exception as _pc_err:
        # Shadow-fail — the call still works without a greeting.
        logger.warning("[persona_call] opening greeting skipped: %s", _pc_err)

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
                    _clog("lifecycle_hangup", sid=sid, reason="user_ended")
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
                # Protocol sentinels are NOT user utterances — they
                # exist solely so the frontend can signal state
                # transitions (phase machine nudges, etc.) without
                # the LLM reacting to the literal string. Drop and
                # continue; the phase machine already advances on the
                # first real user utterance, so no special handling
                # is required here beyond not running the turn.
                if text_in in _PROTOCOL_SENTINELS:
                    continue
                _clog("turn_user_in", sid=sid, text_len=len(text_in))
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

                # ── Streaming vs unary turn — additive branch ──────
                # When VOICE_CALL_STREAMING_ENABLED=true the turn runs
                # through turn_stream.run_turn_streaming and emits
                # ``assistant.partial`` + ``assistant.turn_end`` envelopes
                # so the client's streaming TTS can begin speaking long
                # before the full reply has arrived. When the flag is
                # off we take the original path byte-for-byte.
                if cfg.streaming_enabled:
                    turn_id = f"t_{uuid.uuid4().hex[:12]}"
                    token = _barge_in.new_token(sid, turn_id)
                    assistant_text_parts: list[str] = []
                    end_reason = "complete"
                    try:
                        if (
                            _pc_cfg is not None
                            and _pc_cfg.enabled
                            and _pc_facets_obj is not None
                        ):
                            # Filler scheduler still wraps streaming —
                            # if the FIRST delta takes > N ms the
                            # client still gets a ``hmm…`` event.
                            async with _pc_latency.FillerScheduler(
                                send=_pc_send,
                                facets=_pc_facets_obj,
                                cfg=_pc_cfg,
                                session_id=sid,
                            ):
                                index = 0
                                async for delta in turn_stream.run_turn_streaming(
                                    user_text=text_in,
                                    model=model,
                                    auth_bearer=query_bearer,
                                    additional_system=pc_additional_system,
                                    cancel_token=token,
                                ):
                                    if token.is_cancelled():
                                        break
                                    assistant_text_parts.append(delta)
                                    await _send(
                                        ws, "assistant.partial",
                                        {
                                            "turn_id": turn_id,
                                            "delta": delta,
                                            "index": index,
                                        },
                                        session_id=sid,
                                    )
                                    index += 1
                        else:
                            index = 0
                            async for delta in turn_stream.run_turn_streaming(
                                user_text=text_in,
                                model=model,
                                auth_bearer=query_bearer,
                                additional_system=pc_additional_system,
                                cancel_token=token,
                            ):
                                if token.is_cancelled():
                                    break
                                assistant_text_parts.append(delta)
                                await _send(
                                    ws, "assistant.partial",
                                    {
                                        "turn_id": turn_id,
                                        "delta": delta,
                                        "index": index,
                                    },
                                    session_id=sid,
                                )
                                index += 1
                        if token.is_cancelled():
                            end_reason = "cancelled"
                    except Exception as exc:
                        logger.warning("[voice_call] stream turn failed: %s", exc)
                        end_reason = "error"
                    finally:
                        # Always emit turn_end so the client can close
                        # the turn bookkeeping cleanly.
                        _barge_in.clear_session(sid)
                        assistant_text = "".join(assistant_text_parts)
                        await _send(
                            ws, "assistant.turn_end",
                            {
                                "turn_id": turn_id,
                                "reason": end_reason,
                                "full_text": assistant_text,
                            },
                            session_id=sid,
                        )
                        _clog(
                            "turn_assistant_out",
                            sid=sid,
                            turn_id=turn_id,
                            reason=end_reason,
                            text_len=len(assistant_text),
                            route="stream",
                        )
                else:
                    try:
                        if (
                            _pc_cfg is not None
                            and _pc_cfg.enabled
                            and _pc_facets_obj is not None
                        ):
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
                    _clog(
                        "turn_assistant_out",
                        sid=sid,
                        text_len=len(assistant_text),
                        route="unary",
                    )

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

            elif evt_type == "user.barge_in":
                # Phase 3 — cooperative cancel. Client's VAD detected
                # user speech-start while the persona was mid-reply.
                # § 4.4 of the streaming design doc.
                if not (cfg.streaming_enabled and cfg.barge_in_enabled):
                    continue
                turn_id = (payload.get("turn_id") or "").strip()
                if not turn_id:
                    continue
                cancelled = _barge_in.cancel_active(sid, turn_id)
                if cancelled:
                    # Emit the ack IMMEDIATELY — client stops TTS on
                    # receipt, shaving ~50-100 ms off the perceived
                    # barge-in latency vs waiting for the generator
                    # to notice the event on its next poll.
                    await _send(
                        ws, "assistant.cancel",
                        {"turn_id": turn_id, "cause": "user_barge_in"},
                        session_id=sid,
                    )
                    _clog("barge_in", sid=sid, turn_id=turn_id, cause="user_barge_in")
                # Else: stale turn_id (turn already ended). Silent drop.

            elif evt_type == "transcript.partial":
                # Secondary barge-in signal — if the client's explicit
                # user.barge_in didn't arrive but the STT started
                # decoding words, that also means the user spoke.
                # Only fires while a turn is active.
                if not (cfg.streaming_enabled and cfg.barge_in_enabled):
                    continue
                active = _barge_in.get_active(sid)
                if active is not None and not active.is_cancelled():
                    cancelled = _barge_in.cancel_active(sid, active.turn_id)
                    if cancelled:
                        await _send(
                            ws, "assistant.cancel",
                            {
                                "turn_id": active.turn_id,
                                "cause": "user_partial",
                            },
                            session_id=sid,
                        )

            else:
                # Forward-compat: unknown event type is a no-op, not an
                # error. Older servers + newer clients stay friendly.
                pass
    except WebSocketDisconnect:
        # Client dropped — park the session as 'interrupted' so a resume
        # request within the window can pick it back up.
        _barge_in.clear_session(sid)
        service.mark_interrupted(sid)
    except Exception as exc:
        logger.exception("[voice_call] ws error for %s: %s", sid, exc)
        try:
            await _send_error(ws, sid, "internal", "Internal error")
        except Exception:
            pass
        _barge_in.clear_session(sid)
        service.mark_interrupted(sid)
    finally:
        _clog("lifecycle_close", sid=sid)
        _barge_in.clear_session(sid)
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
