"""Practice: a rehearsal that talks back (batch MS27, wave W9).

Practice is the mode where the assistant plays the *other* side — the interviewer, the
examiner, the sceptical customer — and the user rehearses against it. It is the only mode that
speaks aloud, and it does that by running as a **voice call** rather than by growing a second
voice stack inside MeetingSense.

**Through `voice_call/`, not beside it.** That subsystem already owns turn-taking, streaming,
resume tokens, the session policy that decides who may open a call, and — the piece that
matters most here — `barge_in.py`, which is how a person interrupts a machine that is talking.
A rehearsal where the user cannot cut in mid-sentence is not a rehearsal; it is a podcast. So
this module *opens* a voice-call session and hands it a brief, and everything after that is
voice_call's.

**Barge-in is the feature, not a nicety.** In an interview the interesting moments are the
interruptions: the follow-up that lands before you finish, the "sorry, can I stop you there".
`barge_in.new_token` is taken when the assistant starts a turn and `cancel_active` when the
user's speech arrives, and the turn stops on its next poll.

**Nothing here synthesises audio.** `voice_out.py` does that, and only on the desktop app,
because a browser tab cannot put sound into a meeting's microphone.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence

from .. import store

log = logging.getLogger(__name__)

#: Artifact kind a rehearsal brief is stored under.
BRIEF_KIND = "rehearsal"

#: The rehearsal shapes this mode knows. Closed, like every other vocabulary here: an unknown
#: kind is a rehearsal nobody wrote a brief for, and improvising one is how a mock interview
#: becomes an argument.
KINDS = ("interview", "exam", "pitch", "negotiation")


def set_brief(
    meeting_id: str,
    *,
    kind: str,
    role: str = "",
    notes: str = "",
) -> Optional[Dict[str, Any]]:
    """Set up the rehearsal. ``None`` if the shape is one this mode does not know.

    `role` is who the assistant plays — "a sceptical CFO", "the external examiner". `notes` is
    whatever the user wants it to push on. Both optional: a bare "interview" is a usable
    rehearsal, and demanding a paragraph before the user can start is how a rehearsal feature
    goes unused.
    """
    shape = (kind or "").strip().lower()
    if shape not in KINDS:
        return None
    body = {"kind": shape, "role": (role or "").strip(), "notes": (notes or "").strip()}
    try:
        store.add_artifact(meeting_id, kind=BRIEF_KIND, target=shape, detail=json.dumps(body))
    except Exception:  # noqa: BLE001
        log.exception("meetingsense: could not store a rehearsal brief for %s", meeting_id)
        return None
    return body


def brief(meeting_id: str) -> Optional[Dict[str, Any]]:
    """The rehearsal this meeting is set up for, or ``None``. The last one set wins."""
    try:
        rows = store.artifacts_for_meeting(meeting_id, kind=BRIEF_KIND)
    except Exception:  # noqa: BLE001
        return None
    for row in reversed(rows):
        try:
            body = json.loads(row.get("detail") or "")
        except ValueError:
            continue
        if isinstance(body, dict) and body.get("kind") in KINDS:
            return body
    return None


SHAPES: Dict[str, str] = {
    "interview": "You are interviewing the user for a role. Ask one question at a time, follow "
                 "up on what they actually said, and press where a real interviewer would.",
    "exam": "You are examining the user on this subject. Ask one question at a time, start "
            "where they are comfortable and move outward until they reach their edge.",
    "pitch": "You are the person the user is pitching to. Be interested and unconvinced. Ask "
             "the question that decides it.",
    "negotiation": "You are negotiating against the user. Hold your position, concede only "
                   "for something, and never split the difference to be pleasant.",
}


def system_prompt(body: Optional[Dict[str, Any]]) -> str:
    """The brief, as the thing driving the call reads it.

    Built from the shape's own paragraph plus the user's role and notes. A rehearsal with no
    brief gets the generic Practice framing and no shape, which is `mode_prompts`' job — this
    returns ``""`` rather than inventing an interview nobody asked for.
    """
    if not body:
        return ""
    shape = SHAPES.get(body.get("kind") or "", "")
    if not shape:
        return ""
    parts = [shape]
    role = (body.get("role") or "").strip()
    if role:
        parts.append(f"You are playing: {role}.")
    notes = (body.get("notes") or "").strip()
    if notes:
        parts.append(f"What the user asked you to push on: {notes}")
    parts.append("Stay in role. Break character only if the user asks you to.")
    return "\n".join(parts)


# ── opening the call ────────────────────────────────────────────────────────


def open_call(
    meeting_id: str,
    *,
    user_id: str,
    conversation_id: Optional[str] = None,
    persona_id: Optional[str] = None,
    create: Any = None,
    cfg: Any = None,
) -> Dict[str, Any]:
    """Start the rehearsal as a voice call. Returns what happened; never raises.

    `create` is `voice_call.service.create_session`, injected — so a test needs no voice stack,
    and so MeetingSense holds no second opinion about who may open a call. **The policy check
    is theirs**: `create_session` gates on the caller's entitlement, and a MeetingSense path
    that skipped it would be a second door into the same room.

    Returns ``{"ok": False, "reason": …}`` rather than raising, because this is reached from a
    socket carrying a meeting and a refused rehearsal must not end a recording.
    """
    body = brief(meeting_id)
    if not body:
        return {"ok": False, "reason": "this meeting has no rehearsal set up"}
    if create is None:
        return {"ok": False, "reason": "voice calls are not available on this install"}
    try:
        session = create(
            user_id=user_id,
            conversation_id=conversation_id,
            persona_id=persona_id,
            entry_mode="meetingsense_practice",
            client_platform="desktop",
            app_version=None,
            cfg=cfg,
        )
    except Exception as error:  # noqa: BLE001 — a refused call is never worth the meeting
        log.exception("meetingsense: could not open a rehearsal call for %s", meeting_id)
        return {"ok": False, "reason": f"could not start the call: {error}"}

    call_id = (session or {}).get("id")
    if not call_id:
        return {"ok": False, "reason": "the call did not start"}
    _record(meeting_id, call_id)
    # The resume token is deliberately not echoed here. `create_session`'s own docstring says
    # callers must keep it out of anything that lands in a log, and a meeting frame is a thing
    # that lands in a log.
    return {"ok": True, "call_id": call_id, "kind": body["kind"],
            "system": system_prompt(body)}


def _record(meeting_id: str, call_id: str) -> None:
    """Note which call this rehearsal ran in. Never raises."""
    try:
        store.add_artifact(meeting_id, kind=BRIEF_KIND, target="call", detail=f"call:{call_id}")
    except Exception:  # noqa: BLE001
        log.debug("meetingsense: could not record the rehearsal call", exc_info=True)


def calls(meeting_id: str) -> List[str]:
    """Voice-call ids this rehearsal has used, oldest first."""
    try:
        rows = store.artifacts_for_meeting(meeting_id, kind=BRIEF_KIND)
    except Exception:  # noqa: BLE001
        return []
    return [(r.get("detail") or "")[5:] for r in rows
            if (r.get("detail") or "").startswith("call:")]


# ── barge-in ────────────────────────────────────────────────────────────────


def interrupt(call_id: str, *, registry: Any = None, turn_id: Optional[str] = None) -> bool:
    """The user spoke while the assistant was talking. Stop it.

    Straight through to `voice_call/barge_in.py` — the registry that already owns this, whose
    `cancel_active` refuses a stale `turn_id` so an interruption racing a new turn is a silent
    no-op rather than a turn cancelled by accident.

    With no `turn_id`, the active turn is looked up and cancelled, which is the
    `transcript.partial` path: speech arriving is a barge-in whether or not the client
    bothered to say which turn it was interrupting.
    """
    if registry is None:
        from ...voice_call import barge_in as registry  # type: ignore[no-redef]
    if not call_id:
        # A fast path, not a correctness guard: the registry would answer False for a session
        # id it has never seen. It is here so a client that lost its call id does not make a
        # registry lookup out of every partial transcript it sends.
        return False
    try:
        target = turn_id
        if target is None:
            token = registry.get_active(call_id)
            if token is None:
                return False
            target = token.turn_id
        return bool(registry.cancel_active(call_id, target))
    except Exception:  # noqa: BLE001 — a failed interrupt is never worth the call
        log.exception("meetingsense: barge-in failed for %s", call_id)
        return False
