"""The session protocol, as pure logic (spec v1.1 §6.9).

Separated from ``session.py`` on purpose. The batch plan says to build the contract tests
from ``tests/fixtures/protocol/*.json`` **before** the endpoints, and a protocol that can
only be exercised through a live WebSocket is one nobody tests properly. Everything that
decides *what* to say lives here; ``session.py`` only moves bytes.

Two rules from §6.9 that are easy to get wrong and are therefore tested directly:

* **An unknown ``type`` is ignored, silently.** That is what lets addendum v1.2 add
  ``display``, ``adult_ack`` and ``streak`` without a version bump. Answering an unknown
  type with an error would make every future addition a breaking change.
* **A server intent gets no special powers.** The server may only name emotes from the
  whitelist. The client checks again — this is belt and braces, and the belt is here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .rtc import VOICE_CLIENT_TYPES, VOICE_SERVER_TYPES

PROTOCOL_VERSION = 1

#: Client → server, §6.9 and addendum §14.3, plus B10's voice uplink.
CLIENT_TYPES = (
    frozenset({"hello", "ctx", "user_event", "vision_ask", "chat_meta", "pong", "adult_verify_request", "streak"})
    | VOICE_CLIENT_TYPES
)

#: Server → client. Listed so a typo in an emitter is caught here rather than on a headset.
SERVER_TYPES = (
    frozenset({"intent", "say", "vision_insight", "scene", "error", "ping", "display", "adult_ack"})
    | VOICE_SERVER_TYPES
)

#: §6.2's emote whitelist. The server may not invent names any more than the model may.
EMOTE_WHITELIST = frozenset(
    {
        "happy", "sad", "angry", "surprised", "thinking", "celebrate", "dance", "wave",
        "flirt", "tease", "shy", "agree", "disagree", "idle", "point", "lean_in",
        "nod_along", "breathe", "console",
    }
)

HEARTBEAT_SECONDS = 15


@dataclass
class SessionState:
    """What the server knows about one connected client."""

    client: str = ""
    caps: List[str] = field(default_factory=list)
    authenticated: bool = False
    mode: Optional[str] = None
    activity: Optional[str] = None
    attention: float = 0.0
    last_event: Optional[str] = None
    streaks: Dict[str, int] = field(default_factory=dict)
    adult_verified: bool = False
    capture_consent: bool = False


class ProtocolHandler:
    """Turns one client message into zero or more server messages.

    Deliberately synchronous and side-effect free apart from its own state: the transport
    decides when to send, this decides what.
    """

    def __init__(self, *, authenticate=None, now=time.time, voice=None, vision=None) -> None:
        self.state = SessionState()
        self._authenticate = authenticate or (lambda token: bool(token))
        self._now = now
        self.ignored: List[str] = []
        #: B10's uplink, or None on a server with the voice gate off. The handler routes to
        #: it and holds no opinion of its own about audio.
        self.voice = voice
        #: B15's vision service, or None. Same arrangement: this decides nothing about it.
        self.vision = vision
        #: Messages queued by something other than an inbound message — B17's tool bridge,
        #: and B16's curiosity when it lands a turn. The transport drains it; nothing here
        #: sends, because this class has never had a socket and should not grow one.
        self.outbox: List[Dict[str, Any]] = []

    # ── inbound ──────────────────────────────────────────────────────────────

    def handle(self, message: Any) -> List[Dict[str, Any]]:
        """Handle one inbound message. Never raises on bad input."""
        if not isinstance(message, dict):
            return [self.error("bad_message", "expected a JSON object")]

        kind = message.get("type")
        if not isinstance(kind, str):
            return [self.error("bad_message", "missing type")]

        if message.get("v") != PROTOCOL_VERSION:
            return [self.error("bad_version", f"this server speaks v{PROTOCOL_VERSION}")]

        if kind not in CLIENT_TYPES:
            # Forward compatibility (§6.9): a peer that knows more than we do is not an
            # error. Record it for the debug endpoint and say nothing.
            self.ignored.append(kind)
            return []

        if kind != "hello" and not self.state.authenticated:
            return [self.error("unauthenticated", "send hello first")]

        return getattr(self, f"_on_{kind}")(message)

    def _on_hello(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not self._authenticate(message.get("auth")):
            return [self.error("unauthorized", "pairing rejected")]
        self.state.client = str(message.get("client") or "")
        self.state.caps = list(message.get("caps") or [])
        self.state.authenticated = True
        return [self.ping()]

    def _on_ctx(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        self.state.mode = message.get("mode")
        self.state.activity = message.get("activity")
        attention = message.get("attention")
        self.state.attention = float(attention) if isinstance(attention, (int, float)) else 0.0
        return []

    def _on_user_event(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        name = message.get("name")
        self.state.last_event = name
        # B11's consent state, as the client reports it. No new message type: `user_event`
        # is exactly "something happened on the client", and consent starting or stopping
        # is that. §6.14 reads `capture_consent` before any tool may touch a frame.
        if name == "capture:start":
            self.state.capture_consent = True
        elif name == "capture:stop":
            self.state.capture_consent = False
        return []

    def _on_vision_ask(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        """B15, and every answer here is a refusal — deliberately.

        §6.9 sends the frame itself as a data-channel message keyed by ``frameId``. B10
        shipped transcript mode rather than WebRTC, so this session has no data channel and
        no bytes can reach the server this way. Rather than accept an ask it can never
        answer, the handler says so and names the endpoint that does take frames.

        The consent check still happens here and happens first, because §6.14 makes it a
        precondition of *asking*, not of uploading: a client without live capture consent is
        told about the consent, not about the endpoint.

        Nothing in this method touches or holds a frame. There is nowhere in this handler
        that could.
        """
        if self.vision is None:
            return [self.error("vision_unavailable", "vision is not enabled on this server")]
        if not self.state.capture_consent:
            # A server-side permission is not the same as the user having opted in on the
            # device holding the screen.
            return [self.error("vision_no_consent", "no active capture consent on the client")]
        return [self.error("vision_use_endpoint", "POST the frame to /avatar/vision/insight")]

    def _on_chat_meta(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        return []

    def _on_pong(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        return []

    def _on_streak(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        activity = message.get("activity")
        value = message.get("value")
        if isinstance(activity, str) and isinstance(value, int):
            self.state.streaks[activity] = value
        return []

    def _on_voice_offer(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self._voice(message)

    def _on_voice_ice(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self._voice(message)

    def _on_voice_transcript(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self._voice(message)

    def _on_voice_end(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self._voice(message)

    def _voice(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Route to B10's uplink. Absent one, refuse by name rather than ignore.

        The §6.9 ignore rule is for types this server has never heard of. These it has heard
        of, and a client that offered its microphone deserves a no rather than silence.
        """
        if self.voice is None:
            return [self.error("voice_unavailable", "the voice uplink is not enabled")]
        return self.voice.handle(message)

    def _on_adult_verify_request(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        # B28 implements attestation. Refusing by default is the only safe stub: a
        # placeholder that answered "verified" would be the exact failure §16.2 forbids.
        return [self.error("adult_unavailable", "adult verification is not configured")]

    # ── outbound ─────────────────────────────────────────────────────────────

    def intent(self, name: str, intensity: float = 0.6, source: str = "server") -> Dict[str, Any]:
        """Build an intent. Refuses to name an emote outside the whitelist."""
        if name not in EMOTE_WHITELIST:
            raise ValueError(f"{name!r} is not a whitelisted emote")
        return {"v": PROTOCOL_VERSION, "type": "intent", "name": name, "intensity": intensity, "source": source}

    def say(self, text: str, source: str = "server") -> Dict[str, Any]:
        return {"v": PROTOCOL_VERSION, "type": "say", "text": text, "source": source}

    def scene(self, scene_id: str) -> Dict[str, Any]:
        return {"v": PROTOCOL_VERSION, "type": "scene", "id": scene_id}

    def ping(self) -> Dict[str, Any]:
        return {"v": PROTOCOL_VERSION, "type": "ping"}

    def error(self, code: str, msg: str) -> Dict[str, Any]:
        return {"v": PROTOCOL_VERSION, "type": "error", "code": code, "msg": msg}
