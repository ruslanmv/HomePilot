"""avatar_control — the bridge from a tool call to a live avatar (spec v1.1 §6.14, B17).

## The invariant this exists to keep

§6.14: *tools speak intents at turn cadence; client Tier-1 resolves; nothing on the frame
path.* So no tool here names a clip to play. `play_animation` sends an **intent**, and the
client's selector and ranker decide what that looks like — the same path a parsed
``[[emote:…]]`` tag takes, subject to the same §6.5 gates. A tool server that could name a
clip would be a second animation authority, and the whole point of Tier 1 is that there is
one.

The consequence is the acceptance criterion "killing the tool server changes nothing
locally": every gesture the avatar can make, it can make without this. The tool server adds
a *sender*, not a capability. Pull the plug and the client keeps reflexing, selecting,
blending and speaking, because none of that ever ran here.

## Where the safety table is enforced

Once, in :func:`invoke`, reading ``safety.py``. §6.14 maps each tool onto HomePilot's
existing three-level model, and anything absent from the table is ``confirm`` — the safe
default for an unknown tool is to ask, not to act. Tools that touch capture need more than
a level: they need the *client's* consent state to be live, because a server-side approval
is not the same as the user having opted in on the device holding the camera.

## No live session is an error, never a silent drop

An MCP client that asks for a gesture and gets ``{"ok": true}`` while nothing happens has
been lied to. Every refusal here names itself.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from . import safety
from .protocol import EMOTE_WHITELIST, PROTOCOL_VERSION

log = logging.getLogger("avatar_director.control")

#: The tools this bridge implements. A superset would be a tool with no safety row.
TOOLS = tuple(safety.TOOL_SAFETY)

#: A queued sequence may not be longer than this. An MCP client that queues two hundred
#: clips has taken the avatar away from its user for ten minutes.
MAX_SEQUENCE = 8

#: Scenes the client ships (B14). Naming one it does not have is a refusal, not a no-op.
KNOWN_SCENES = frozenset({"forest", "ocean", "meditation"})


class ManifestRegistry:
    """A read-only view of the client's animation manifest, if this install has one.

    The knowledge base lives in the client repository — it is authored alongside the assets
    it describes, and copying it here would give two answers to "what can she do". So this
    reads the one file, at a path the deployment names, and the two read-only tools refuse
    by name when there is none. A search that quietly returned nothing would be worse.
    """

    def __init__(self, records: Optional[List[Dict[str, Any]]] = None) -> None:
        self.records = records or []

    @classmethod
    def from_jsonl(cls, path: str) -> Optional["ManifestRegistry"]:
        import json  # noqa: PLC0415
        import os  # noqa: PLC0415

        if not path or not os.path.isfile(path):
            return None
        records = []
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue  # one torn line must not cost the rest of the file
        return cls(records)

    def get(self, clip_id: str) -> Optional[Dict[str, Any]]:
        for record in self.records:
            if record.get("id") == clip_id:
                return record
        return None

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Substring over description, tags and intents.

        Deliberately not the client's TF-IDF selector: that runs on the device against the
        blackboard's live mood, and reproducing it here would be a second ranking that
        disagreed with the first. Searching the catalogue is a different job from Tier 1
        choosing a clip, and this is the catalogue one.
        """
        needle = query.lower().strip()
        if not needle:
            return []
        words = [w for w in needle.split() if w]
        scored = []
        for record in self.records:
            haystack = " ".join(
                [
                    str(record.get("id") or ""),
                    str(record.get("description") or ""),
                    " ".join(record.get("tags") or []),
                    " ".join(record.get("intents") or []),
                ]
            ).lower()
            hits = sum(1 for word in words if word in haystack)
            if hits:
                scored.append((hits, record))
        scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("id"))))
        return [
            {
                "id": r.get("id"),
                "description": r.get("description"),
                "intents": r.get("intents"),
                "energy": r.get("energy"),
                "duration": (r.get("stats") or {}).get("duration"),
            }
            for _, r in scored[:limit]
        ]


class ControlError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _ok(**payload: Any) -> Dict[str, Any]:
    return {"ok": True, **payload}


class AvatarControl:
    """One instance per backend process. Holds no avatar state — it forwards."""

    def __init__(self, *, sessions: Callable[[], Dict[str, Any]], registry=None, now=time.time) -> None:
        self._sessions = sessions
        self.registry = registry
        self.now = now
        self.calls: Dict[str, int] = {}
        self.refusals: Dict[str, int] = {}

    # ── the one live session ─────────────────────────────────────────────────

    def _live(self):
        """The session to act on, or a refusal. One avatar, one session; if a second ever
        connects, acting on 'the first one' silently would be worse than saying so."""
        live = list(self._sessions().values())
        authenticated = [s for s in live if getattr(s.state, "authenticated", False)]
        if not authenticated:
            raise ControlError("no_session", "no avatar is connected")
        if len(authenticated) > 1:
            raise ControlError("ambiguous_session", f"{len(authenticated)} avatars are connected")
        return authenticated[0]

    # ── the gate ─────────────────────────────────────────────────────────────

    def check(self, tool: str, *, approved: bool = False) -> str:
        """The safety decision for one call, or a refusal. Returns the level it passed at.

        `approved` is the caller telling us a human said yes — Context Forge's own confirm
        flow. It is not a way around the consent check below it, which is about the client
        rather than about the operator.
        """
        if tool not in safety.TOOL_SAFETY:
            # Not "unknown tool, ignore": an unknown tool is `confirm` by §6.14's default,
            # and this bridge does not implement it, so it is a refusal either way.
            raise ControlError("unknown_tool", f"{tool!r} has no safety level and is not implemented")

        level = safety.level_for(tool)
        if level == "confirm" and not approved:
            raise ControlError("needs_confirmation", f"{tool} is 'confirm' and no approval was passed")

        if tool in safety.REQUIRES_CLIENT_CONSENT:
            session = self._live()
            if not getattr(session.state, "capture_consent", False):
                # A server-side approval is not the same as the user having opted in on the
                # device holding the camera. Both, or neither.
                raise ControlError("no_client_consent", f"{tool} needs live capture consent on the client")
        return level

    # ── tools ────────────────────────────────────────────────────────────────

    def invoke(self, tool: str, args: Optional[Dict[str, Any]] = None, *, approved: bool = False) -> Dict[str, Any]:
        """One tool call. Every path returns or raises; nothing returns ok for a no-op."""
        args = args or {}
        try:
            level = self.check(tool, approved=approved)
            result = getattr(self, f"_{tool}")(args)
        except ControlError as error:
            self.refusals[error.code] = self.refusals.get(error.code, 0) + 1
            raise
        self.calls[tool] = self.calls.get(tool, 0) + 1
        result.setdefault("safety", level)
        return result

    # read-only ---------------------------------------------------------------

    def _search_animations(self, args: Dict[str, Any]) -> Dict[str, Any]:
        query = str(args.get("query") or "").strip()
        limit = max(1, min(20, int(args.get("limit") or 5)))
        if not query:
            raise ControlError("bad_args", "search_animations needs a query")
        if self.registry is None:
            raise ControlError("no_registry", "the animation knowledge base is not loaded on this server")
        return _ok(results=self.registry.search(query, limit=limit), query=query)

    def _get_animation(self, args: Dict[str, Any]) -> Dict[str, Any]:
        clip_id = str(args.get("id") or "").strip()
        if not clip_id:
            raise ControlError("bad_args", "get_animation needs an id")
        if self.registry is None:
            raise ControlError("no_registry", "the animation knowledge base is not loaded on this server")
        record = self.registry.get(clip_id)
        if record is None:
            raise ControlError("not_found", f"no animation {clip_id!r}")
        return _ok(animation=record)

    # autonomous --------------------------------------------------------------

    def _play_animation(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Sends an *intent*, not a clip. §6.14's bridge invariant, in one method."""
        name = str(args.get("intent") or args.get("name") or "").strip()
        if name not in EMOTE_WHITELIST:
            raise ControlError("not_whitelisted", f"{name!r} is not a §6.2 emote")
        intensity = _intensity(args.get("intensity"))
        sent = self._send({
            "v": PROTOCOL_VERSION,
            "type": "intent",
            "name": name,
            "intensity": intensity,
            "source": "tool",
        })
        return _ok(sent=sent, intent=name, note="Tier 1 chooses the clip; this names an intent")

    def _queue_sequence(self, args: Dict[str, Any]) -> Dict[str, Any]:
        raw = args.get("intents") or args.get("sequence") or []
        if not isinstance(raw, list) or not raw:
            raise ControlError("bad_args", "queue_sequence needs a list of intents")
        if len(raw) > MAX_SEQUENCE:
            raise ControlError("sequence_too_long", f"at most {MAX_SEQUENCE} intents")

        steps: List[Dict[str, Any]] = []
        for entry in raw:
            name = str(entry.get("intent") or entry.get("name") or "") if isinstance(entry, dict) else str(entry)
            if name not in EMOTE_WHITELIST:
                # Refuse the whole sequence rather than half of it. A partial performance is
                # harder for a caller to reason about than none.
                raise ControlError("not_whitelisted", f"{name!r} is not a §6.2 emote")
            steps.append({
                "name": name,
                "intensity": _intensity(entry.get("intensity") if isinstance(entry, dict) else None),
            })

        sent = 0
        for step in steps:
            # One message per step, in order. The client's scheduler handles the crossfades
            # and the minimum play times (§6.6); nothing here decides timing.
            sent += self._send({
                "v": PROTOCOL_VERSION,
                "type": "intent",
                "name": step["name"],
                "intensity": step["intensity"],
                "source": "tool",
            })
        return _ok(sent=sent, steps=[s["name"] for s in steps])

    def _set_mood(self, args: Dict[str, Any]) -> Dict[str, Any]:
        valence = _unit(args.get("valence"), -1.0, 1.0)
        energy = _unit(args.get("energy"), 0.0, 1.0)
        if valence is None and energy is None:
            raise ControlError("bad_args", "set_mood needs valence or energy")
        sent = self._send({
            "v": PROTOCOL_VERSION,
            "type": "display",
            "kind": "mood",
            "data": {"valence": valence, "energy": energy},
        })
        return _ok(sent=sent, valence=valence, energy=energy)

    def _set_scene(self, args: Dict[str, Any]) -> Dict[str, Any]:
        scene = str(args.get("id") or args.get("scene") or "").strip()
        if scene not in KNOWN_SCENES:
            raise ControlError("unknown_scene", f"{scene!r} is not one of {sorted(KNOWN_SCENES)}")
        return _ok(sent=self._send({"v": PROTOCOL_VERSION, "type": "scene", "id": scene}), scene=scene)

    # confirm + client consent ------------------------------------------------

    def _vision_insight(self, args: Dict[str, Any]) -> Dict[str, Any]:
        prompt = str(args.get("prompt") or "").strip()
        sent = self._send({
            "v": PROTOCOL_VERSION,
            "type": "display",
            "kind": "vision_request",
            "data": {"prompt": prompt},
        })
        # The frame does not travel through here — §6.13's endpoint takes it, from the
        # client, with the client's own consent. This asks; it does not fetch.
        return _ok(sent=sent, note="the client answers over /avatar/vision/insight")

    def _start_capture(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self._capture_request("start", args)

    def _stop_capture(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self._capture_request("stop", args)

    def _capture_request(self, action: str, args: Dict[str, Any]) -> Dict[str, Any]:
        source = str(args.get("source") or "screen")
        sent = self._send({
            "v": PROTOCOL_VERSION,
            "type": "display",
            "kind": "capture_request",
            "data": {"action": action, "source": source},
        })
        # Even here the client decides. The server asks for a capture; B11's machine is what
        # grants one, and it is on the other side of this socket.
        return _ok(sent=sent, action=action, note="the client's consent machine decides")

    # ── transport ────────────────────────────────────────────────────────────

    def _send(self, message: Dict[str, Any]) -> int:
        """Queue one message on the live session. Returns how many were queued (0 or 1)."""
        session = self._live()
        outbox = getattr(session, "outbox", None)
        if outbox is None:
            raise ControlError("no_session", "the connected avatar has no outbox")
        outbox.append(message)
        return 1

    @property
    def stats(self) -> Dict[str, Any]:
        return {"calls": dict(self.calls), "refusals": dict(self.refusals), "tools": list(TOOLS)}


def _intensity(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.6
    return max(0.0, min(1.0, number))


def _unit(value: Any, low: float, high: float) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(low, min(high, number))


# ── transport: the loopback route the MCP server calls ───────────────────────


def build_router(config, *, control: Optional[AvatarControl] = None):
    """``POST /avatar/control`` — in-process, and reachable over loopback by the MCP server.

    The MCP server is a separate process on its own port; this is how it reaches the live
    socket, and it is the same loopback shape ``voice_call.turn`` already uses to reach the
    chat endpoint.
    """
    from fastapi import APIRouter, HTTPException  # noqa: PLC0415 — lazy, like session.py
    from pydantic import BaseModel, Field  # noqa: PLC0415

    class ControlRequest(BaseModel):
        tool: str
        args: Dict[str, Any] = Field(default_factory=dict)
        approved: bool = False

    # This module has `from __future__ import annotations`, so the endpoint's parameter
    # annotation below is the *string* "ControlRequest", and Pydantic resolves a string
    # annotation against the function's `__globals__` — the module namespace — where a class
    # defined inside this function does not exist.
    #
    # Pydantic 2.13 happens to fall back to the enclosing frame's locals and finds it anyway;
    # the version this project pins, 2.7.4, does not, and raises PydanticUndefinedAnnotation.
    # So the route built fine on a developer's machine and failed in CI, which is the whole
    # reason the pin is in requirements.txt.
    #
    # Publishing the model into the module namespace is what makes the annotation resolvable
    # on both, while keeping the pydantic import lazy — this package deliberately imports
    # without FastAPI installed, and hoisting the model to module scope would end that.
    globals()["ControlRequest"] = ControlRequest

    router = APIRouter(tags=["avatar-director"])
    registry = ManifestRegistry.from_jsonl(getattr(getattr(config, "kb", None), "manifest", "") or "")
    bridge = control or AvatarControl(sessions=_default_sessions, registry=registry)

    @router.post("/avatar/control")
    async def control_endpoint(body: ControlRequest) -> Dict[str, Any]:  # pragma: no cover - transport
        try:
            return bridge.invoke(body.tool, body.args, approved=body.approved)
        except ControlError as error:
            status = {
                "no_session": 409,
                "ambiguous_session": 409,
                "no_client_consent": 403,
                "needs_confirmation": 403,
                "unknown_tool": 404,
                "not_found": 404,
            }.get(error.code, 400)
            raise HTTPException(status_code=status, detail={"code": error.code, "msg": error.detail}) from error

    return router


def _default_sessions() -> Dict[str, Any]:
    from .session import sessions  # noqa: PLC0415 — lazy; control.py imports no transport

    return sessions()
