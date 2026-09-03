"""The meeting session (batch MS2).

**This module must never import FastAPI.** That is not tidiness; it is the whole point of the
batch. MeetingSense has to run over two transports — a WebSocket the browser opens directly,
and the avatar session that OllaBridge proxies for a hosted page — and a core that knows
about either one has to be written twice.

So the core knows about :class:`Transport`, which is two methods. MS3 implements it over a
FastAPI WebSocket; MS7 implements it over the avatar session's outbox. Neither changes a line
in here, and a test implements it with a list.

State is ``idle → live → ended``, one way. There is no reopening: a stopped meeting is a
record, and a second ``stop`` is a no-op rather than an error, because both ends of a socket
notice a disconnect and both will try.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Sequence

from . import store
from .transcript import UtteranceAssembler

#: One JSON frame on the wire. Deliberately a plain dict: the frame vocabulary belongs to the
#: protocol documented in the design, and a dataclass per type here would be a second place
#: to keep it in step.
Frame = Dict[str, Any]


class Transport(Protocol):
    """Where a session's frames go.

    Two methods, and no more on purpose. Everything a transport might also want to expose —
    the peer address, the negotiated capabilities, whether the socket is still open — is
    knowledge the core would then start branching on, and branching on it is how one core
    becomes two.

    ``send`` is awaited. A transport that buffers may return immediately; one that writes to a
    socket may not, and the core must not care which.
    """

    async def send(self, frame: Frame) -> None: ...

    async def close(self) -> None: ...


class ListTransport:
    """A transport that keeps frames in a list. Used by tests, and by nothing else.

    It lives in the module it serves rather than in the test file because MS3 and MS7 both
    need it to prove they produce the *same* frames as each other, and a fake defined twice
    stops being the same fake.
    """

    def __init__(self) -> None:
        self.frames: List[Frame] = []
        self.closed = False

    async def send(self, frame: Frame) -> None:
        self.frames.append(frame)

    async def close(self) -> None:
        self.closed = True

    def types(self) -> List[str]:
        return [f.get("type", "") for f in self.frames]

    def of_type(self, kind: str) -> List[Frame]:
        return [f for f in self.frames if f.get("type") == kind]


class MeetingState:
    IDLE = "idle"
    LIVE = "live"
    ENDED = "ended"


class MeetingSessionError(RuntimeError):
    """A refusal the caller should turn into an ``error`` frame, with a stable code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class MeetingSession:
    """One meeting, from ``start`` to ``stop``.

    :param transport: where frames go
    :param config: a :class:`~.config.MeetingSenseConfig`
    :param transcribe: ``async (audio, fmt, duration_s) -> [span]``. Injected rather than
        fetched, so a test needs no speech stack and MS3 can hold one provider per
        connection — the thing MS1 made cheap and this makes explicit.
    :param now: injected clock. ``undefined`` would be a hidden dependency on wall time in
        every duration this class reports.
    """

    def __init__(
        self,
        *,
        transport: Transport,
        config: Any,
        transcribe: Optional[Callable[..., Awaitable[Sequence[Dict[str, Any]]]]] = None,
        now: Callable[[], float] = time.time,
        meeting_id: Optional[str] = None,
    ) -> None:
        self.transport = transport
        self.config = config
        self._transcribe = transcribe
        self._now = now
        self.meeting_id = meeting_id or uuid.uuid4().hex
        self.state = MeetingState.IDLE
        self.started_at: Optional[float] = None
        self.ended_at: Optional[float] = None
        self.conversation_id: Optional[str] = None
        self.audio_mode: Optional[str] = None
        self.mic_muted = False
        self.assembler = UtteranceAssembler()
        self.segment_count = 0
        self.keyframe_count = 0

    # ── lifecycle ───────────────────────────────────────────────────────────

    @property
    def elapsed_ms(self) -> int:
        """Milliseconds since start; frozen once the meeting ends."""
        if self.started_at is None:
            return 0
        end = self.ended_at if self.ended_at is not None else self._now()
        return max(0, int(round((end - self.started_at) * 1000)))

    async def start(self, message: Frame) -> None:
        """Open the meeting and answer ``ready``."""
        if self.state != MeetingState.IDLE:
            raise MeetingSessionError("already_started", "this session has already started")
        conversation_id = str(message.get("conversation_id") or "").strip()
        if not conversation_id:
            # A meeting with nowhere to land is a meeting nobody can find again.
            raise MeetingSessionError("conversation_required", "start needs a conversation_id")

        self.conversation_id = conversation_id
        self.audio_mode = message.get("audio", {}).get("mode") if isinstance(message.get("audio"), dict) else None
        self.started_at = self._now()
        self.state = MeetingState.LIVE

        store.create_meeting(
            conversation_id=conversation_id,
            project_id=message.get("project_id"),
            title=message.get("title"),
            source=message.get("source"),
            audio_mode=self.audio_mode,
            retention=getattr(self.config, "retention", "text"),
            meeting_id=self.meeting_id,
            started_at=self.started_at,
        )
        await self.transport.send(
            {
                "type": "ready",
                "meeting_id": self.meeting_id,
                "stt": self._transcribe is not None,
                "notes": bool(message.get("notes")),
                "watch": bool(message.get("watch")),
            }
        )

    async def stop(self) -> Frame:
        """End the meeting and answer ``final``. Idempotent.

        Both ends of a socket notice a disconnect, and both will try to stop. The second
        attempt is not an error to report; it is the same outcome arriving twice.
        """
        if self.state == MeetingState.ENDED:
            return {"type": "final", "meeting_id": self.meeting_id, "segments": self.segment_count}
        if self.state != MeetingState.LIVE:
            raise MeetingSessionError("not_live", "this session was never started")

        self.ended_at = self._now()
        self.state = MeetingState.ENDED
        store.end_meeting(self.meeting_id, ended_at=self.ended_at)
        final: Frame = {
            "type": "final",
            "meeting_id": self.meeting_id,
            "elapsed": self.elapsed_ms,
            "segments": self.segment_count,
            "slides": self.keyframe_count,
        }
        await self.transport.send(final)
        return final

    # ── audio in, segments out ──────────────────────────────────────────────

    async def on_audio(self, message: Frame) -> List[Frame]:
        """Transcribe one chunk and emit whatever it added.

        Returns the ``segment`` frames sent, so a caller can count them without reading the
        transport back. A chunk that was entirely overlap returns ``[]`` — a real outcome,
        not a failure.
        """
        self._require_live()
        if self._transcribe is None:
            raise MeetingSessionError("stt_unavailable", "no speech provider is configured")

        audio = message.get("audio_bytes")
        if not audio:
            raise MeetingSessionError("audio_missing", "an audio frame needs audio")

        t0_ms = int(message.get("t0") or 0)
        t1 = message.get("t1")
        duration_s = None if t1 is None else max(0.0, (float(t1) - t0_ms) / 1000.0)

        spans = await self._transcribe(
            audio,
            fmt=message.get("format") or "wav",
            duration_s=duration_s,
        )
        fresh = self.assembler.push(
            spans or [],
            chunk_t0_ms=t0_ms,
            speaker=message.get("speaker"),
        )
        if not fresh:
            return []

        ids = store.add_segments(self.meeting_id, fresh)
        self.segment_count += len(ids)

        sent: List[Frame] = []
        for seg_id, seg in zip(ids, fresh):
            frame = {
                "type": "segment",
                "id": seg_id,
                "t0": seg["t0_ms"],
                "t1": seg["t1_ms"],
                "speaker": seg.get("speaker"),
                "text": seg["text"],
                "conf": seg.get("conf"),
            }
            await self.transport.send(frame)
            sent.append(frame)
        return sent

    async def on_keyframe(self, message: Frame) -> Optional[str]:
        """Record a slide keyframe. Captioning is MS9's; this only stores and counts."""
        self._require_live()
        url = message.get("url")
        if not url:
            raise MeetingSessionError("url_required", "a keyframe needs a url")
        kid = store.add_keyframe(
            self.meeting_id,
            t_ms=int(message.get("t") or self.elapsed_ms),
            url=url,
            hash=message.get("hash"),
        )
        self.keyframe_count += 1
        return kid

    async def on_mute(self, message: Frame) -> None:
        """Mute state is the client's to decide; the server records it and echoes status.

        Kept here rather than left to the client alone because the recording pill and the
        card may be on different surfaces — a hosted avatar and the HomePilot web UI can both
        be watching one meeting, and only the server knows what both should show.
        """
        self._require_live()
        self.mic_muted = bool(message.get("mic"))
        await self.send_status()

    async def send_status(self, **extra: Any) -> Frame:
        frame: Frame = {
            "type": "status",
            "meeting_id": self.meeting_id,
            "state": self.state,
            "elapsed": self.elapsed_ms,
            "segments": self.segment_count,
            "slides": self.keyframe_count,
            "mic_muted": self.mic_muted,
            **extra,
        }
        await self.transport.send(frame)
        return frame

    async def send_error(self, code: str, detail: str) -> Frame:
        """Errors use the shape the avatar protocol already uses, so one client handles both."""
        frame = {"type": "error", "code": code, "msg": detail}
        await self.transport.send(frame)
        return frame

    def _require_live(self) -> None:
        if self.state != MeetingState.LIVE:
            raise MeetingSessionError("not_live", f"session is {self.state}, not live")


# ── registry ────────────────────────────────────────────────────────────────

#: Live sessions by meeting id. In-memory on purpose: a session is a socket and a socket does
#: not survive a restart. What survives is in the store, and a restart ends the meeting rather
#: than resuming a stream nobody is holding.
_SESSIONS: Dict[str, MeetingSession] = {}


def register(session: MeetingSession) -> None:
    _SESSIONS[session.meeting_id] = session


def unregister(meeting_id: str) -> None:
    _SESSIONS.pop(meeting_id, None)


def get(meeting_id: str) -> Optional[MeetingSession]:
    return _SESSIONS.get(meeting_id)


def live_sessions() -> Dict[str, MeetingSession]:
    """Every live session. MS18's context provider reads this to find a conversation's."""
    return {mid: s for mid, s in _SESSIONS.items() if s.state == MeetingState.LIVE}


def for_conversation(conversation_id: str) -> Optional[MeetingSession]:
    """The live meeting attached to a conversation, if there is one."""
    for session in live_sessions().values():
        if session.conversation_id == conversation_id:
            return session
    return None
