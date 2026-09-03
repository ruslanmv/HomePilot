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

import asyncio
import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Sequence

from . import store
from .transcript import UtteranceAssembler

#: One JSON frame on the wire. Deliberately a plain dict: the frame vocabulary belongs to the
#: protocol documented in the design, and a dataclass per type here would be a second place
#: to keep it in step.
Frame = Dict[str, Any]

log = logging.getLogger(__name__)

#: How long `stop` waits for captions still in flight. A keyframe is captured at most once
#: every eight seconds, so at most one request is usually outstanding; this is the ceiling on
#: how much a slow vision model may delay the end of a meeting.
CAPTION_DRAIN_S = 8.0


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


class _DetachedTransport:
    """Where frames go while a meeting is suspended: nowhere.

    A suspended session must not hold the socket that died — a write to it raises, and the
    raise would land in whatever code path was mid-way through handling a timer. Swallowing
    instead is safe because nothing *should* be sending: every entry point checks the state
    first, and this is the backstop for the one that forgets.
    """

    async def send(self, frame: Frame) -> None:
        return None

    async def close(self) -> None:
        return None


class MeetingState:
    IDLE = "idle"
    LIVE = "live"
    #: Dropped, but still resumable (D10). A separate state rather than a flag on LIVE,
    #: because everything that refuses when not live must keep refusing here: a suspended
    #: meeting has no socket, so accepting audio for it would transcribe into a void.
    SUSPENDED = "suspended"
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
        notes: Any = None,
        vision: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
        now: Callable[[], float] = time.time,
        meeting_id: Optional[str] = None,
    ) -> None:
        self.transport = transport
        self.config = config
        self._transcribe = transcribe
        #: MS12's engine, or None. Injected like `transcribe` and for the same reason: a test
        #: needs no model, and the core keeps no opinion about where notes come from.
        self.notes = notes
        #: MS9's ``analyze_image``, or None. None means slides are recorded and not captioned,
        #: which is a complete meeting on an install with no vision model — not a degraded one.
        self.vision = vision
        self._now = now
        self.meeting_id = meeting_id or uuid.uuid4().hex
        self.state = MeetingState.IDLE
        self.started_at: Optional[float] = None
        self.ended_at: Optional[float] = None
        self.conversation_id: Optional[str] = None
        self.audio_mode: Optional[str] = None
        #: Declared by `start`. Kept on the session because a resume arrives on a new socket
        #: that never sent a `start`, and the channel count decides how its audio is split.
        self.audio_channels: int = 1
        self.mic_muted = False
        # One assembler per speaker. The 200 ms overlap is an artefact of how *one* stream
        # was chunked, so removing it across streams would compare the microphone against
        # the system audio and drop whichever of two people said the same words second —
        # picking the speaker by which channel happened to be transcribed first.
        self.assemblers: Dict[str, UtteranceAssembler] = {}
        self.segment_count = 0
        self.keyframe_count = 0
        #: Captioning tasks still in flight. Held so `stop` can wait briefly for them and a
        #: test can await them deterministically instead of sleeping.
        self.caption_tasks: List[Any] = []
        #: Monotonic per-meeting numbering of outbound segments. The client reports the last
        #: one it saw when it resumes, which is the only way to know what died in the socket.
        self.seq = 0
        self.suspended_at: Optional[float] = None
        #: The task that ends this meeting when its grace window runs out. Held so a resume
        #: can cancel it and a test can await it.
        self.expiry_task: Any = None

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
        audio = message.get("audio") if isinstance(message.get("audio"), dict) else {}
        self.audio_mode = audio.get("mode")
        try:
            self.audio_channels = max(1, int(audio.get("channels") or 1))
        except (TypeError, ValueError):
            self.audio_channels = 1
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
        # MS16. Recorded here rather than on stop: a meeting that never ends — a server
        # restart mid-recording — should still bring its card back when the chat is reopened,
        # and nothing on a chat message says which meeting produced it.
        try:
            store.add_thread(self.meeting_id, conversation_id, kind="origin",
                             created_at=self.started_at)
        except Exception:  # noqa: BLE001 — a missing link is a card that does not hydrate
            log.exception("meetingsense: could not record the thread for %s", self.meeting_id)

        await self.transport.send(
            {
                "type": "ready",
                "meeting_id": self.meeting_id,
                "stt": self._transcribe is not None,
                "notes": bool(message.get("notes")),
                "watch": bool(message.get("watch")),
            }
        )

    # ── suspend and resume (D10) ────────────────────────────────────────────

    def resumable_until(self, grace_s: float) -> Optional[float]:
        """When this meeting stops being resumable, or None while it is live."""
        if self.suspended_at is None:
            return None
        return self.suspended_at + max(0.0, grace_s)

    def suspend(self, *, at: Optional[float] = None) -> None:
        """The socket died. Hold the meeting open rather than ending it.

        Nothing is sent — there is no socket to send it to — and the transport is dropped so a
        stray write cannot go to a closed connection. Everything that makes the transcript
        continuous is kept: the assemblers with their overlap windows, the counters, `seq`.
        Rebuilding those on resume would restart the overlap dedupe and duplicate a line at
        every reconnection.
        """
        if self.state != MeetingState.LIVE:
            raise MeetingSessionError("not_live", f"session is {self.state}, not live")
        self.suspended_at = at if at is not None else self._now()
        self.state = MeetingState.SUSPENDED
        self.transport = _DetachedTransport()
        store.suspend_meeting(self.meeting_id, suspended_at=self.suspended_at)

    async def resume(self, transport: Transport, *, last_seq: int = 0, max_replay: int = 200) -> List[Frame]:
        """Re-attach a new socket to this meeting and hand back what it missed.

        Returns the frames sent: a ``resumed`` frame, then any segments numbered above
        ``last_seq``. D10 says the server replays nothing because the client already has it —
        which is true of everything that arrived, and false of exactly the frames that were in
        flight when the socket died. Those exist only in the store, so replaying them is what
        makes "no gap in seq" true rather than aspirational.
        """
        if self.state != MeetingState.SUSPENDED:
            raise MeetingSessionError("not_suspended", f"session is {self.state}, not suspended")
        if not store.resume_meeting(self.meeting_id):
            # The store disagrees — the meeting ended underneath us. Believe the store.
            raise MeetingSessionError("not_resumable", "this meeting is no longer resumable")

        self.transport = transport
        self.state = MeetingState.LIVE
        self.suspended_at = None
        if self.expiry_task is not None:
            self.expiry_task.cancel()
            self.expiry_task = None

        sent: List[Frame] = [
            {
                "type": "resumed",
                "meeting_id": self.meeting_id,
                "elapsed": self.elapsed_ms,
                "segments": self.segment_count,
                "slides": self.keyframe_count,
                "seq": self.seq,
            }
        ]
        await self.transport.send(sent[0])

        for row in store.segments_after_seq(self.meeting_id, last_seq, limit=max_replay):
            frame = {
                "type": "segment",
                "id": row["id"],
                "seq": row["seq"],
                "t0": row["t0_ms"],
                "t1": row["t1_ms"],
                "speaker": row.get("speaker"),
                "text": row["text"],
                "conf": row.get("conf"),
                "replayed": True,
            }
            await self.transport.send(frame)
            sent.append(frame)
        return sent

    async def stop(self) -> Frame:
        """End the meeting and answer ``final``. Idempotent.

        Both ends of a socket notice a disconnect, and both will try to stop. The second
        attempt is not an error to report; it is the same outcome arriving twice.
        """
        if self.state == MeetingState.ENDED:
            return {"type": "final", "meeting_id": self.meeting_id, "segments": self.segment_count}
        if self.state not in (MeetingState.LIVE, MeetingState.SUSPENDED):
            raise MeetingSessionError("not_live", "this session was never started")

        # A meeting that ends out of its grace window ends at the moment the socket dropped,
        # not two minutes later when a timer noticed. The elapsed time a card shows should be
        # how long people were talking.
        self.ended_at = self.suspended_at if self.suspended_at is not None else self._now()
        self.state = MeetingState.ENDED

        # The final window, forced: without this the last minute of every meeting is missing
        # from its notes, and the summary is built from an incomplete picture.
        if self.notes is not None:
            try:
                final_notes = await self.notes.run(force=True)
                if final_notes is not None:
                    await self.transport.send(final_notes)
            except Exception:  # noqa: BLE001
                log.exception("meetingsense: final notes failed for %s", self.meeting_id)
        # Captions still in flight, briefly: the summary message is written below, and a
        # caption that lands a second after it is a caption nobody reads.
        await self.drain_captions()
        store.end_meeting(self.meeting_id, ended_at=self.ended_at)
        final: Frame = {
            "type": "final",
            "meeting_id": self.meeting_id,
            "elapsed": self.elapsed_ms,
            "segments": self.segment_count,
            "slides": self.keyframe_count,
        }
        await self.transport.send(final)
        # The meeting lands in its conversation here rather than in the route, so both
        # transports get it: MS7's avatar session ends a meeting through this same method.
        # Best-effort by construction — see finalize.finalize_meeting.
        from . import finalize

        finalize.finalize_meeting(self.meeting_id)

        # MS15, and deliberately last: the client already has `final`, so the time this takes
        # is time nobody is waiting on. A meeting that cannot be embedded is still a complete
        # meeting — the transcript is in SQLite, which is the copy that cannot be rebuilt, and
        # this one can be by re-indexing.
        from . import retrieval

        retrieval.index_meeting(self.meeting_id)
        return final

    # ── audio in, segments out ──────────────────────────────────────────────

    def assembler_for(self, speaker: Optional[str]) -> UtteranceAssembler:
        """The assembler for one speaker, created on first sight of them."""
        key = speaker or ""
        if key not in self.assemblers:
            self.assemblers[key] = UtteranceAssembler()
        return self.assemblers[key]

    async def _spans(self, message: Frame) -> Sequence[Dict[str, Any]]:
        """Transcribe one frame's audio. Shared by the stored path and the provisional one."""
        if self._transcribe is None:
            raise MeetingSessionError("stt_unavailable", "no speech provider is configured")
        audio = message.get("audio_bytes")
        if not audio:
            raise MeetingSessionError("audio_missing", "an audio frame needs audio")
        t1 = message.get("t1")
        t0_ms = int(message.get("t0") or 0)
        duration_s = None if t1 is None else max(0.0, (float(t1) - t0_ms) / 1000.0)
        return await self._transcribe(
            audio,
            fmt=message.get("format") or "wav",
            # The client framed this audio and knows how long it is; the provider may not,
            # and a provider that only returns text would otherwise report `t1: None` for a
            # span whose length was never in doubt.
            duration_s=duration_s,
        )

    async def on_audio(self, message: Frame) -> List[Frame]:
        """Transcribe one chunk and emit whatever it added.

        Returns the ``segment`` frames sent, so a caller can count them without reading the
        transport back. A chunk that was entirely overlap returns ``[]`` — a real outcome,
        not a failure.
        """
        self._require_live()
        speaker = message.get("speaker")
        spans = await self._spans(message)
        fresh = self.assembler_for(speaker).push(
            spans or [],
            chunk_t0_ms=int(message.get("t0") or 0),
            speaker=speaker,
        )
        if not fresh:
            return []

        # Numbered before they are stored, so the row and the frame carry the same `seq` and
        # a replay can reproduce the frame exactly.
        for seg in fresh:
            self.seq += 1
            seg["seq"] = self.seq
        ids = store.add_segments(self.meeting_id, fresh)
        self.segment_count += len(ids)

        sent: List[Frame] = []
        for seg_id, seg in zip(ids, fresh):
            frame = {
                "type": "segment",
                "id": seg_id,
                "seq": seg["seq"],
                "t0": seg["t0_ms"],
                "t1": seg["t1_ms"],
                "speaker": seg.get("speaker"),
                "text": seg["text"],
                "conf": seg.get("conf"),
            }
            await self.transport.send(frame)
            sent.append(frame)

        await self._maybe_notes(fresh)
        return sent

    async def _maybe_notes(self, fresh: List[Frame]) -> Optional[Frame]:
        """Feed the notes engine and push a `notes` frame when it produced one.

        Guarded rather than assumed: an install with no model reachable records a perfectly
        good transcript, and a notes engine that could take the meeting down with it would be
        a worse trade than having no notes.
        """
        if self.notes is None:
            return None
        try:
            self.notes.add(fresh)
            if not self.notes.due():
                return None
            frame = await self.notes.run()
        except Exception:  # noqa: BLE001 — notes are never worth a meeting
            log.exception("meetingsense: notes failed for %s", self.meeting_id)
            return None
        if frame is not None:
            await self.transport.send(frame)
        return frame

    async def on_partial(self, message: Frame) -> List[Frame]:
        """Transcribe a frame provisionally: emit ``partial``, store nothing, remember nothing.

        A partial is the client saying "this utterance is still open, here is what I have so
        far". The same audio arrives again when the utterance closes, so feeding it to the
        assembler would make the closing chunk look like a duplicate of itself and the real
        segment would be trimmed away. Provisional text is shown and then replaced; it is
        never a record.
        """
        self._require_live()
        t0_ms = int(message.get("t0") or 0)
        spans = await self._spans(message)
        sent: List[Frame] = []
        for span in spans or []:
            text = (span.get("text") or "").strip()
            if not text:
                continue
            frame = {
                "type": "partial",
                "t0": int(round(float(span.get("t0") or 0.0) * 1000)) + t0_ms,
                "speaker": span.get("speaker") or message.get("speaker"),
                "text": text,
            }
            await self.transport.send(frame)
            sent.append(frame)
        return sent

    async def on_keyframe(self, message: Frame) -> Optional[str]:
        """Record a slide keyframe, and start captioning it (MS9).

        The row is written synchronously and the caption is not. A vision model takes seconds,
        and this coroutine runs inside the frame loop that is also carrying audio: awaiting the
        model here would stall the transcript for the length of every caption. The keyframe is
        in the store either way, so a caption that never arrives costs a description, not a
        slide.
        """
        self._require_live()
        url = message.get("url")
        if not url:
            raise MeetingSessionError("url_required", "a keyframe needs a url")
        t_ms = int(message.get("t") or self.elapsed_ms)
        hash_ = message.get("hash")
        kid = store.add_keyframe(self.meeting_id, t_ms=t_ms, url=url, hash=hash_)
        self.keyframe_count += 1
        # Announced before it is captioned, and again once it is (MS10). The strip has to show
        # a slide the moment it is taken — an install with no vision model would otherwise have
        # an empty strip for a meeting full of slides, and a slide that appears three seconds
        # late looks like a slide that was missed. A client upserts on `id`.
        await self.transport.send(
            {"type": "slide", "id": kid, "t": t_ms, "url": url, "hash": hash_,
             "caption": None, "reused": False}
        )
        self._start_caption(kid, url=url, hash_=hash_, t_ms=t_ms)
        return kid

    def _start_caption(self, keyframe_id: str, *, url: str, hash_: Optional[str], t_ms: int) -> Any:
        """Schedule captioning for one keyframe. Returns the task, or ``None``.

        No vision, no task. The reuse path in :mod:`.keyframes` needs no model — it copies a
        caption already written — but on an install with no vision there was never a first
        caption to copy, so scheduling would only queue work that resolves to nothing.
        """
        if self.vision is None:
            return None
        try:
            loop = asyncio.get_event_loop()
            task = loop.create_task(self._caption(keyframe_id, url=url, hash_=hash_, t_ms=t_ms))
        except RuntimeError:  # pragma: no cover — no running loop is not a meeting
            log.debug("meetingsense: no loop to caption %s on", keyframe_id)
            return None
        self.caption_tasks.append(task)
        task.add_done_callback(lambda t: self.caption_tasks.remove(t) if t in self.caption_tasks else None)
        return task

    async def _caption(self, keyframe_id: str, *, url: str, hash_: Optional[str], t_ms: int) -> None:
        """Caption one keyframe and push the `slide` frame. Never raises, never blocks a stop."""
        from . import keyframes as keyframes_mod

        try:
            frame = await keyframes_mod.caption(
                self.meeting_id,
                keyframe_id,
                url=url,
                hash=hash_,
                t_ms=t_ms,
                model=getattr(getattr(self.config, "vision", None), "model", "") or "",
                analyze=self.vision,
            )
        except Exception:  # noqa: BLE001 — a caption is never worth the meeting
            log.exception("meetingsense: captioning raised for %s", keyframe_id)
            return
        if frame is None:
            return
        try:
            await self.transport.send(frame)
        except Exception:  # noqa: BLE001 — the socket may be gone; the caption is stored
            log.debug("meetingsense: could not send a slide frame for %s", keyframe_id, exc_info=True)

    async def drain_captions(self, timeout: float = CAPTION_DRAIN_S) -> int:
        """Wait, briefly, for captions still in flight. Returns how many did not finish.

        Called from `stop` so the summary message the meeting leaves behind carries the last
        slide's caption rather than a blank line. Bounded, because a hung vision request must
        not hold a meeting open.

        What does not finish is **cancelled**, not merely stopped being waited for. A task
        left running after the session ended holds the transport it would write a `slide`
        frame to, and would write it to a socket belonging to a meeting that is over. The
        keyframe row survives with no caption, which is the same outcome as no vision model.
        """
        pending = [t for t in list(self.caption_tasks) if not t.done()]
        if not pending:
            return 0
        try:
            _, unfinished = await asyncio.wait(pending, timeout=max(0.0, timeout))
        except Exception:  # noqa: BLE001
            return len(pending)
        for task in unfinished:
            task.cancel()
        return len(unfinished)

    async def on_mute(self, message: Frame) -> None:
        """Mute state is the client's to decide; the server records it and echoes status.

        Kept here rather than left to the client alone because the recording pill and the
        card may be on different surfaces — a hosted avatar and the HomePilot web UI can both
        be watching one meeting, and only the server knows what both should show.
        """
        self._require_live()
        self.mic_muted = bool(message.get("mic"))
        await self.send_status()

    async def send_status(self, *, grace_s: float = 0.0, **extra: Any) -> Frame:
        frame: Frame = {
            "type": "status",
            "meeting_id": self.meeting_id,
            "state": self.state,
            "elapsed": self.elapsed_ms,
            "segments": self.segment_count,
            "slides": self.keyframe_count,
            "mic_muted": self.mic_muted,
            "seq": self.seq,
            "resumable_until": self.resumable_until(grace_s),
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


async def expire_if_due(session: MeetingSession, *, grace_s: float, now: float) -> bool:
    """End a suspended meeting whose grace window has run out. Returns whether it did.

    A function rather than a sleep so the decision can be tested against a clock instead of a
    stopwatch: the caller schedules the wait, this decides the outcome.
    """
    if session.state != MeetingState.SUSPENDED:
        return False
    deadline = session.resumable_until(grace_s)
    if deadline is not None and now < deadline:
        return False
    await session.stop()
    unregister(session.meeting_id)
    return True


def suspended_sessions() -> Dict[str, MeetingSession]:
    return {mid: s for mid, s in _SESSIONS.items() if s.state == MeetingState.SUSPENDED}


def for_conversation(conversation_id: str) -> Optional[MeetingSession]:
    """The live meeting attached to a conversation, if there is one."""
    for session in live_sessions().values():
        if session.conversation_id == conversation_id:
            return session
    return None
