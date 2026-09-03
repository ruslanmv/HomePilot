"""MeetingSense over the avatar session (batch MS7).

This is the batch MS2 was written for. A hosted page — yourfriend.online — cannot open a
WebSocket to `ws://localhost`, but it already holds one to the avatar session, and OllaBridge
already proxies that as a pipe. So a meeting reaches a local HomePilot over a socket that
exists, with no new URL and no second token.

**Nothing about the meeting is re-implemented here.** The core is MS2's `MeetingSession`; the
audio decoding is MS3's `audio.py`; the per-frame routing is MS3's own `_handle_audio`. What
this file adds is a `Transport` — two methods — and an envelope. That is the entire cost of
the second transport, and it is the whole return on MS2 having refused to import FastAPI.

The consequence worth stating: the two transports cannot answer differently, because there is
only one thing answering. A test drives the same script through both and compares frames.

Wire shape, deliberately boring::

    client → server   {"v":1,"type":"meeting_start", "conversation_id":…, "audio":{…}}
                      {"v":1,"type":"meeting_audio", "format":"wav", "data_b64":…, "t0":…}
                      {"v":1,"type":"meeting_stop"}
    server → client   {"v":1,"type":"meeting","meeting":{…}}     ← an MS3 frame, verbatim

One outbound type carrying the MS3 frame untouched, rather than a flattened family of
`meeting_segment` / `meeting_status` / `meeting_final`. A client that already renders the
local transcript keeps working by reading `.meeting`, and a new server frame needs no change
here at all.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..avatar_director.protocol import PROTOCOL_VERSION
from . import audio as audio_wire
from . import session as session_mod
from . import store
from .config import load_config

log = logging.getLogger(__name__)

#: The one server type this batch adds. Everything a meeting says rides inside it.
MEETING_FRAME = "meeting"


def envelope(frame: Dict[str, Any]) -> Dict[str, Any]:
    """Wrap an MS3 frame for the avatar socket, without altering it."""
    return {"v": PROTOCOL_VERSION, "type": MEETING_FRAME, "meeting": frame}


class AvatarTransport:
    """MS2's :class:`~.session.Transport`, over the avatar handler's outbox.

    Two forwarding methods, exactly as the local WebSocket transport is. It writes to the
    handler's outbox rather than to the socket because that socket already has exactly one
    writer — the session loop — and adding a second is how interleaved frames and half-written
    JSON happen.
    """

    def __init__(self, outbox: List[Dict[str, Any]]) -> None:
        self._outbox = outbox

    async def send(self, frame: Dict[str, Any]) -> None:
        self._outbox.append(envelope(frame))

    async def close(self) -> None:
        # The avatar socket outlives the meeting: it carries the persona, the gestures and the
        # voice channel too. Closing it because a meeting ended would take the avatar down
        # with it.
        return None


class MeetingBridge:
    """One meeting per avatar session, driven by the frames the handler queued.

    Holds the session rather than the registry doing it, because an avatar socket is
    long-lived and may run several meetings in a row — and because when it drops, the same
    grace window MS3-a gives a local client should apply here.
    """

    def __init__(self, outbox: List[Dict[str, Any]], *, config=None, transcribe=None, now=None) -> None:
        self.outbox = outbox
        self.config = config or load_config()
        self.session: Optional[session_mod.MeetingSession] = None
        self._transcribe = transcribe
        self._provider_loaded = transcribe is not None
        #: Passed through to the session. MS2 made the clock injectable so a duration could be
        #: asserted rather than tolerated; a bridge that hid it again would take that back,
        #: and the parity test would have to accept "close enough" instead of "the same".
        self._now = now

    # ── the speech provider ─────────────────────────────────────────────────

    def _provider(self):
        """One provider for this socket, fetched on first use.

        Not at construction: an avatar session that never records a meeting should not load a
        speech model, and most of them never will.
        """
        if self._provider_loaded:
            return self._transcribe
        self._provider_loaded = True
        try:
            from ..voice.providers import get_stt_provider

            provider = get_stt_provider()
            if getattr(provider, "available", False):

                async def transcribe(data: bytes, *, fmt: str = "wav", duration_s=None):
                    return await provider.transcribe_segments(data, fmt=fmt, duration_s=duration_s)

                self._transcribe = transcribe
        except Exception as exc:  # noqa: BLE001
            log.warning("meetingsense: no speech provider on the avatar session (%s)", exc)
        return self._transcribe

    # ── inbound ─────────────────────────────────────────────────────────────

    async def handle(self, message: Dict[str, Any]) -> None:
        """Act on one queued meeting frame. Never raises.

        A meeting that goes wrong must not take the avatar session with it: the same socket is
        carrying the persona, the gestures and possibly a spoken conversation, and dropping
        all of that because a chunk of audio was malformed would be a poor trade.
        """
        kind = message.get("type")
        try:
            if not self.config.enabled:
                await self._refuse("disabled", "MeetingSense is disabled on this server")
                return
            # The remote flag is separate from the master on purpose: an operator who wants
            # meetings on their own machine has not thereby agreed to accept them from a
            # hosted page.
            if not self.config.flags.remote:
                await self._refuse(
                    "remote_disabled",
                    "this server does not accept meetings over the avatar session",
                )
                return

            if kind == "meeting_start":
                await self._start(message)
            elif kind == "meeting_audio":
                await self._audio(message)
            elif kind == "meeting_stop":
                await self._stop()
            # Anything else queued here is a type a later wave added. Ignored, per §6.9.
        except session_mod.MeetingSessionError as exc:
            await self._refuse(exc.code, exc.detail)
        except audio_wire.AudioFrameError as exc:
            await self._refuse(exc.code, exc.detail)
        except Exception as exc:  # noqa: BLE001
            log.exception("meetingsense: avatar %s frame failed", kind)
            await self._refuse("frame_failed", f"{kind} failed: {exc}")

    async def handle_all(self, messages) -> None:
        for message in messages:
            await self.handle(message)

    async def _start(self, message: Dict[str, Any]) -> None:
        if self.session is not None and self.session.state == session_mod.MeetingState.LIVE:
            await self._refuse("already_started", "this session is already recording")
            return
        store.migrate_if_enabled(self.config)
        transcribe = self._provider()
        kwargs = {"now": self._now} if self._now is not None else {}
        from . import keyframes as keyframes_mod
        from . import notes_engine as notes_engine_mod

        self.session = session_mod.MeetingSession(
            transport=AvatarTransport(self.outbox),
            config=self.config,
            transcribe=transcribe,
            # MS9, and the same value the local socket gets: a meeting proxied in from a
            # hosted page captions its slides on this machine's vision model, because that is
            # the only machine in the picture that has one.
            vision=keyframes_mod.vision_bridge(self.config),
            # MS12-a, and the same factory the local socket uses: a meeting proxied in from a
            # hosted page takes notes on this machine's model, like everything else it does.
            notes_factory=notes_engine_mod.engine_factory(self.config),
            **kwargs,
        )
        await self.session.start(message)
        session_mod.register(self.session)

    async def _audio(self, message: Dict[str, Any]) -> None:
        if self.session is None:
            raise session_mod.MeetingSessionError("not_live", "no meeting has been started")
        # MS3's own splitter, not a second copy: this is where a stereo frame becomes two
        # speakers, and two implementations of that would drift into swapping them.
        from .routes import _handle_audio

        await _handle_audio(self.session, message, self.session.audio_channels)

    async def _stop(self) -> None:
        if self.session is None:
            raise session_mod.MeetingSessionError("not_live", "no meeting has been started")
        await self.session.stop()
        session_mod.unregister(self.session.meeting_id)

    async def close(self) -> None:
        """The avatar socket went. Give the meeting the same grace a local client gets.

        Reusing MS3-a rather than ending it here: somebody on a hosted page loses their
        connection for the same reasons and deserves the same answer.
        """
        if self.session is None or self.session.state != session_mod.MeetingState.LIVE:
            return
        if self.config.resume.grace_s <= 0:
            await self.session.stop()
            session_mod.unregister(self.session.meeting_id)
            return
        self.session.suspend()

    async def _refuse(self, code: str, detail: str) -> None:
        """An error frame, in the meeting envelope, with the socket left alone.

        The same ``{code, msg}`` shape MS3 uses, so a client handles one error format across
        both transports — which was the reason MS2 chose that shape over the design's `error`.
        """
        self.outbox.append(envelope({"type": "error", "code": code, "msg": detail}))
