"""Voice uplink — mic to persona reply to gesture (spec v1.1 §6.10, batch B10).

This batch is an **integration**, and the integration is the whole point: HomePilot already
has every piece, in two places, and B10's job is to wire them to the avatar session without
growing a third.

* ``app.voice_call.turn.run_turn`` already runs a turn against the chat endpoint with the
  caller's identity, persona and memory. That is the turn path.
* ``app.voice_call.barge_in`` already owns per-session cancellation. That is the barge-in.
* ``app.voice.providers.get_stt_provider`` already wraps Whisper-API and faster-whisper.
  That is the ASR — and a media terminus (below) must call it rather than be one.

Nothing here transcribes, runs a model, or decides what an assistant says.

## Two media modes, and why the default is the one without WebRTC

``voice.media = "transcript"`` is the shipped default. The client runs the recogniser it
already has and sends final text up; the server never touches audio. It is the path that
works today, and it is not a shortcut — ``voice_call`` was built for exactly this shape
(``transcript.final`` from the client), for the same reason: browsers have a recogniser and
shipping a second one server-side buys latency, not accuracy.

``voice.media = "webrtc"`` terminates the media server-side instead. That needs a media
terminus — an object that can take an SDP offer and hand back text — and this module does
not ship one, because doing it properly means ``aiortc`` and a codec stack, which is a
deployment decision rather than a code one. The terminus is **injected**. With none
installed an offer is refused with ``voice_media_unavailable``, following the rule B8 set
with ``vision_unavailable``: a stub that refuses is honest, a stub that accepts an offer it
cannot honour leaves a client waiting on audio nobody will ever answer.

## Marking

Every reply the uplink produces is marked ``source: "voice"`` — on the ``say``, on the
gestures, and on the ``X-HomePilot-Source`` header the turn carries into chat. The client
uses it to tell a spoken exchange from a curiosity remark, and it is deliberately *not*
``"user"``: §6.5 blocks NSFW for any intent whose source is not the user, and a tag written
by a model is a model's tag whichever way the sentence reached it.

Pure module: no FastAPI, no sockets. ``session.py`` moves the bytes and awaits the turn.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("avatar_director.rtc")

PROTOCOL_VERSION = 1

#: Client → server, added by B10. Unknown to a B8-era server, which ignores them (§6.9).
VOICE_CLIENT_TYPES = frozenset({"voice_offer", "voice_ice", "voice_transcript", "voice_end"})

#: Server → client.
VOICE_SERVER_TYPES = frozenset({"voice_answer", "voice_ice", "voice_state"})

#: The media modes this module understands.
MEDIA_MODES = frozenset({"transcript", "webrtc"})

#: §6.8's tag, as the client's parser reads it. One regex, two implementations — the client's
#: is in ``src/behavior/adapters/LLMTagAdapter.js`` and they are tested against each other.
EMOTE_TAG = re.compile(r"\[\[\s*emote\s*:\s*([a-z_]+)\s*([01](?:\.\d+)?)?\s*\]\]", re.IGNORECASE)

#: How long a turn may run before the uplink stops waiting on it.
TURN_TIMEOUT_SEC = 30.0


def split_emote_tags(text: str, whitelist) -> tuple:
    """Split a reply into what is spoken and what is performed.

    The client strips these tags out of streamed chat itself (B4). A ``say`` does not go
    through that path — it goes to the app's ``speakText`` — so a tag left in the string
    would be *read aloud*. Stripping here is not tidiness, it is the difference between a
    gesture and the avatar saying "open bracket open bracket emote colon happy".

    Returns ``(clean_text, [{name, intensity}])``, whitelist-checked. A tag naming something
    outside §6.2 is dropped from the gestures and still stripped from the speech.
    """
    found: List[Dict[str, Any]] = []

    def take(match: "re.Match") -> str:
        name = match.group(1).lower()
        raw = match.group(2)
        if name in whitelist:
            found.append({"name": name, "intensity": float(raw) if raw else 0.6})
        else:
            log.debug("voice reply named a non-whitelisted emote %r — dropped", name)
        return ""

    clean = EMOTE_TAG.sub(take, text or "")
    # Collapse the double spaces a removed tag leaves mid-sentence, and tidy the edges.
    clean = re.sub(r"[ \t]{2,}", " ", clean)
    clean = "\n".join(line.rstrip() for line in clean.split("\n")).strip()
    return clean, found


@dataclass
class Turn:
    """One spoken exchange, in flight or finished."""

    turn_id: str
    text: str
    started_at: float
    cancelled: bool = False
    reply: Optional[str] = None


@dataclass
class UplinkState:
    """What the uplink knows. Read by the tests and by the debug endpoint."""

    negotiated: bool = False
    media: str = ""
    listening: bool = False
    turns: int = 0
    dropped_stale: int = 0
    refusals: List[str] = field(default_factory=list)


class VoiceUplink:
    """The voice half of one session.

    Synchronous by design, apart from :meth:`run_pending`. Everything that decides *what*
    to say is a plain function call the contract tests make directly; the one thing that
    genuinely has to await — the turn against the chat endpoint — is a single method the
    transport drives.
    """

    def __init__(
        self,
        config,
        *,
        whitelist,
        run_turn: Optional[Callable] = None,
        media_terminus: Optional[Any] = None,
        auth_bearer: Optional[str] = None,
        barge_in: Optional[Any] = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.whitelist = whitelist
        self.media_terminus = media_terminus
        self.auth_bearer = auth_bearer
        self.now = now
        self.state = UplinkState()

        # Injected so the contract tests need neither a chat endpoint nor a running loop.
        # The defaults are the existing modules — this uplink implements neither.
        self._run_turn = run_turn
        self._barge_in = barge_in

        self.session_key = uuid.uuid4().hex[:12]
        self.active: Optional[Turn] = None
        self.pending: Optional[Turn] = None

    # ── inbound ──────────────────────────────────────────────────────────────

    def handle(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        """One voice message in, zero or more server messages out. Never raises."""
        kind = message.get("type")
        if not self.config.enabled:
            return [self._refuse("voice_unavailable", "the voice uplink is not enabled")]
        return getattr(self, f"_on_{kind}")(message)

    def _on_voice_offer(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        mode = str(message.get("mode") or self.config.media).lower()
        if mode not in MEDIA_MODES:
            return [self._refuse("voice_bad_mode", f"unknown media mode {mode!r}")]

        if mode == "webrtc":
            if self.media_terminus is None:
                # The honest refusal. See the module header: accepting an offer we cannot
                # answer strands a client on audio nobody will ever transcribe.
                return [
                    self._refuse(
                        "voice_media_unavailable",
                        "this server has no WebRTC media terminus; offer mode 'transcript'",
                    )
                ]
            answer = self.media_terminus.answer(message.get("sdp") or "")
            self.state.negotiated = True
            self.state.media = "webrtc"
            self.state.listening = True
            return [
                {"v": PROTOCOL_VERSION, "type": "voice_answer", "sdp": answer, "mode": "webrtc"},
                self.voice_state("listening"),
            ]

        # transcript mode: nothing to negotiate, which is most of its appeal.
        self.state.negotiated = True
        self.state.media = "transcript"
        self.state.listening = True
        return [
            {"v": PROTOCOL_VERSION, "type": "voice_answer", "sdp": "", "mode": "transcript"},
            self.voice_state("listening"),
        ]

    def _on_voice_ice(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        if self.media_terminus is None:
            # Not a refusal: a client that offered transcript mode and still trickles ICE is
            # harmless, and answering an error for every candidate would be noise.
            return []
        self.media_terminus.add_candidate(message.get("candidate"))
        return []

    def _on_voice_transcript(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not self.state.negotiated:
            return [self._refuse("voice_not_negotiated", "send voice_offer first")]

        text = str(message.get("text") or "").strip()
        if not message.get("final"):
            # Interim text drives the client's own VAD and nothing here. Running a turn on
            # a partial would answer half a sentence.
            return []
        if not text:
            return []

        replies: List[Dict[str, Any]] = []
        if self.active is not None:
            # Barge-in: the user started a new utterance while the last reply was still
            # being produced. voice_call's registry owns cancellation; this asks it, and
            # marks the turn so a reply that arrives anyway is discarded rather than spoken.
            replies.extend(self._cancel_active())

        turn = Turn(turn_id=uuid.uuid4().hex[:12], text=text, started_at=self.now())
        self.active = turn
        self.pending = turn
        self.state.turns += 1
        replies.append(self.voice_state("thinking"))
        return replies

    def _on_voice_end(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        replies = self._cancel_active() if self.active is not None else []
        self.state.listening = False
        if self.media_terminus is not None:
            self.media_terminus.close()
        replies.append(self.voice_state("idle"))
        return replies

    # ── the one asynchronous step ────────────────────────────────────────────

    def take_pending(self) -> Optional[Turn]:
        """Hand the transport the turn it should run, if there is one."""
        turn, self.pending = self.pending, None
        return turn

    async def run_pending(self, turn: Turn) -> List[Dict[str, Any]]:
        """Run one turn against the existing chat path and shape the reply.

        The only await in the module. Failure is a message, never an exception: a chat
        endpoint having a bad minute must not take the session down with it — every other
        channel is still working and the user should be told, not disconnected.
        """
        run_turn = self._run_turn or _default_run_turn
        try:
            reply = await run_turn(
                user_text=turn.text,
                model=self.config.model,
                auth_bearer=self.auth_bearer,
                extra_headers={"X-HomePilot-Source": "voice"},
            )
        except Exception as exc:  # noqa: BLE001 — surfaced to the client, not swallowed
            log.warning("voice turn failed: %s", exc)
            self._finish(turn)
            return [
                {"v": PROTOCOL_VERSION, "type": "error", "code": "voice_turn_failed", "msg": str(exc)[:200]},
                self.voice_state("listening"),
            ]

        if turn.cancelled:
            # The user spoke over her. The reply is real but it answers a question that has
            # already been replaced, so it is dropped rather than spoken late.
            self.state.dropped_stale += 1
            self._finish(turn)
            return []

        turn.reply = reply
        self._finish(turn)
        return self.messages_for(reply)

    def messages_for(self, reply: str) -> List[Dict[str, Any]]:
        """A reply, as the messages that make her speak and move."""
        spoken, gestures = split_emote_tags(reply, self.whitelist)
        messages: List[Dict[str, Any]] = []
        for gesture in gestures:
            messages.append(
                {
                    "v": PROTOCOL_VERSION,
                    "type": "intent",
                    "name": gesture["name"],
                    "intensity": gesture["intensity"],
                    "source": "voice",
                }
            )
        if spoken:
            messages.append({"v": PROTOCOL_VERSION, "type": "say", "text": spoken, "source": "voice"})
        messages.append(self.voice_state("listening"))
        return messages

    # ── outbound helpers ─────────────────────────────────────────────────────

    def voice_state(self, state: str) -> Dict[str, Any]:
        return {"v": PROTOCOL_VERSION, "type": "voice_state", "state": state}

    def _refuse(self, code: str, msg: str) -> Dict[str, Any]:
        self.state.refusals.append(code)
        return {"v": PROTOCOL_VERSION, "type": "error", "code": code, "msg": msg}

    def _cancel_active(self) -> List[Dict[str, Any]]:
        turn = self.active
        if turn is None:
            return []
        turn.cancelled = True
        registry = self._barge_in if self._barge_in is not None else _default_barge_in()
        if registry is not None:
            try:
                registry.cancel_active(self.session_key, turn.turn_id)
            except Exception:  # noqa: BLE001 — a registry miss must not stop the new turn
                log.debug("barge-in registry declined to cancel %s", turn.turn_id)
        return []

    def _finish(self, turn: Turn) -> None:
        if self.active is turn:
            self.active = None


# ── the seams onto the existing modules ──────────────────────────────────────


async def _default_run_turn(**kwargs):
    """The real turn path. Imported here rather than at module scope so this module can be
    read, and its contract tested, without HomePilot's backend requirements installed."""
    from app.voice_call import turn as voice_call_turn  # noqa: PLC0415 — deliberately lazy

    return await voice_call_turn.run_turn(**kwargs)


def _default_barge_in():
    """voice_call's cancellation registry, or ``None`` where it cannot be imported."""
    try:
        from app.voice_call import barge_in  # noqa: PLC0415 — deliberately lazy

        return barge_in
    except Exception:  # noqa: BLE001
        return None


def webrtc_terminus(config):
    """The media terminus for ``voice.media = "webrtc"``, if this deployment can build one.

    Returns ``None`` unless ``aiortc`` is installed, and B10 does not add it to
    ``requirements.txt``: it pulls a codec stack, and whether a deployment wants the server
    holding audio is a deployment's decision. With no terminus the uplink refuses WebRTC
    offers by name, which is a better answer than a dependency nobody asked for.

    A terminus must implement ``answer(sdp) -> sdp``, ``add_candidate(candidate)``,
    ``close()``, and hand transcripts back through the *existing* STT provider
    (``app.voice.providers.get_stt_provider``). It must not be an ASR.
    """
    try:
        import aiortc  # noqa: F401,PLC0415
    except ImportError:
        log.info("no aiortc — the voice uplink will refuse WebRTC offers and serve transcript mode")
        return None
    raise NotImplementedError(
        "aiortc is installed but no media terminus is configured; "
        "see docs/AVATAR_DIRECTOR_BATCHES.md B10"
    )
