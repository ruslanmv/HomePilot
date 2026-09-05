"""Rolling notes and the recap (batch MS12, decision D9 tier 2).

Every 60 seconds or 400 words, whichever comes first, the newest slice of transcript goes to
the model and comes back as a **delta**: what to add, what to resolve. The delta is merged
here, server-side, and the merged notes are pushed to the card.

Three decisions are load-bearing, and each is a defence against a specific failure.

**The trigger is a floor, not a schedule.** A dense two minutes deserves an update and a quiet
ten do not, so words count as well as seconds. A fixed timer would spend tokens on silence and
lag behind an argument.

**Merging happens here, not in the model.** Asking a model for the whole notes object each
pass means every pass can quietly drop a decision the last pass got right, and the card would
rewrite itself under the reader — which §2a forbids for the same reason it forbids editing a
segment already on screen. Deltas can only add and resolve; nothing here deletes.

**A model that answers badly costs one window, never the meeting.** Malformed JSON, prose
wrapped around JSON, a key with the wrong type, a citation pointing at a timestamp that does
not exist — each is dropped and the meeting carries on. The alternative is a transcription
session ending because a language model had an off minute.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from . import prompts, store

log = logging.getLogger(__name__)

#: A model that has been told to answer with JSON and answers with JSON inside prose. Cheaper
#: to tolerate than to argue with, and every local model does it sometimes.
_FENCED = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_delta(raw: Any) -> Dict[str, Any]:
    """Get a delta out of whatever the model said. ``{}`` when there is nothing usable.

    Tolerant in the three ways models actually fail: a fenced block, an object with prose
    around it, and a key whose value is the wrong type. Each returns less rather than raising,
    because the caller's alternative to "no notes this window" is "no meeting".
    """
    if isinstance(raw, dict):
        body: Any = raw
    else:
        text = (raw or "").strip() if isinstance(raw, str) else ""
        if not text:
            return {}
        body = None
        for pattern in (_FENCED, _BARE_OBJECT):
            match = pattern.search(text)
            if not match:
                continue
            try:
                body = json.loads(match.group(1) if pattern is _FENCED else match.group(0))
                break
            except ValueError:
                continue
        if body is None:
            try:
                body = json.loads(text)
            except ValueError:
                return {}
    if not isinstance(body, dict):
        return {}

    delta: Dict[str, Any] = {}
    for key in prompts.DELTA_KEYS:
        value = body.get(key)
        if key == "summary":
            if isinstance(value, str) and value.strip():
                delta[key] = value.strip()
            continue
        if isinstance(value, list):
            items = [i for i in value if isinstance(i, dict) and (i.get("text") or "").strip()]
            if items:
                delta[key] = items
    return delta


def _key(text: str) -> str:
    """How two note items are judged to be the same thing.

    Case- and punctuation-insensitive, because a model asked twice about the same decision
    phrases it twice. Without this the card grows three copies of "ship in October" over a long
    meeting, which is the most obvious way for notes to look broken.
    """
    return " ".join(re.findall(r"[^\W_]+", (text or "").lower()))


def _cited(item: Dict[str, Any], valid_t0: Optional[set]) -> Optional[Dict[str, Any]]:
    """Normalise one item, dropping a citation the transcript cannot support.

    A `t0` the model invented is worse than none: MS13 answers with these, and a timestamp
    that jumps to the wrong minute is the kind of error that makes somebody stop trusting the
    whole feature. So an uncitable item keeps its text and loses its `t0` rather than being
    dropped entirely — the observation may still be right.
    """
    text = (item.get("text") or "").strip()
    if not text:
        return None
    out: Dict[str, Any] = {"text": text}
    raw = item.get("t0")
    if isinstance(raw, (int, float)) and (valid_t0 is None or int(raw) in valid_t0):
        out["t0"] = int(raw)
    owner = item.get("owner")
    if isinstance(owner, str) and owner.strip():
        out["owner"] = owner.strip()
    return out


def merge(notes: Dict[str, Any], delta: Dict[str, Any], *, valid_t0: Optional[set] = None) -> Dict[str, Any]:
    """Apply a delta to the notes. Never deletes; resolving marks rather than removes.

    A resolved question stays visible with `resolved: true` so the card can strike it through.
    Removing it would mean a line the reader saw a minute ago has vanished, and "did I imagine
    that?" is precisely the doubt §2a is built to avoid.
    """
    merged: Dict[str, Any] = {
        "summary": notes.get("summary", ""),
        "decisions": list(notes.get("decisions") or []),
        "actions": list(notes.get("actions") or []),
        "questions": list(notes.get("questions") or []),
    }

    for delta_key, notes_key in (
        ("add_decisions", "decisions"),
        ("add_actions", "actions"),
        ("add_questions", "questions"),
    ):
        seen = {_key(i.get("text", "")) for i in merged[notes_key]}
        for item in delta.get(delta_key) or []:
            normalised = _cited(item, valid_t0)
            if normalised is None:
                continue
            key = _key(normalised["text"])
            if key in seen:
                continue
            seen.add(key)
            merged[notes_key].append(normalised)

    for item in delta.get("resolve_questions") or []:
        key = _key(item.get("text", ""))
        for question in merged["questions"]:
            if _key(question.get("text", "")) == key:
                question["resolved"] = True

    if delta.get("summary"):
        merged["summary"] = delta["summary"]
    return merged


def cap_words(text: str, limit: int = prompts.RECAP_MAX_WORDS) -> str:
    """Hold the recap to its budget.

    Enforced rather than requested. A model told "120 words maximum" will send 200 eventually,
    and D9's whole guarantee is that this block has a known size — a limit that is only a
    suggestion is not a budget.
    """
    words = (text or "").split()
    if len(words) <= limit:
        return (text or "").strip()
    return " ".join(words[:limit]).rstrip(",;:") + "…"


class NotesEngine:
    """Rolling notes for one meeting.

    :param call: ``async (messages, **kw) -> str``. Injected rather than imported so a test
        needs no model, and so the compute router stays a detail of the caller.
    """

    #: D9's trigger. Either is enough — see the module docstring.
    INTERVAL_S = 60
    MAX_WORDS = 400

    def __init__(
        self,
        meeting_id: str,
        *,
        call: Callable[..., Awaitable[str]],
        interval_s: Optional[int] = None,
        max_words: Optional[int] = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.meeting_id = meeting_id
        self._call = call
        self.interval_s = self.INTERVAL_S if interval_s is None else interval_s
        self.max_words = self.MAX_WORDS if max_words is None else max_words
        self._now = now
        self.notes: Dict[str, Any] = {"summary": "", "decisions": [], "actions": [], "questions": []}
        self.recap: str = ""
        self.version = 0
        self._pending: List[Dict[str, Any]] = []
        self._pending_words = 0
        self._last_run = now()

    # ── the trigger ─────────────────────────────────────────────────────────

    def add(self, segments: Sequence[Dict[str, Any]]) -> None:
        """Queue transcribed segments. Cheap: this runs on the transcription path."""
        for segment in segments:
            text = (segment.get("text") or "").strip()
            if not text:
                continue
            self._pending.append(segment)
            self._pending_words += len(text.split())

    @property
    def pending_words(self) -> int:
        return self._pending_words

    def due(self) -> bool:
        """Whether a window is ready. Nothing pending is never due, however long it has been."""
        if not self._pending:
            return False
        return (
            self._pending_words >= self.max_words
            or (self._now() - self._last_run) >= self.interval_s
        )

    # ── the window ──────────────────────────────────────────────────────────

    async def run(self, *, force: bool = False) -> Optional[Dict[str, Any]]:
        """Process one window. Returns the merged notes, or ``None`` if nothing changed.

        ``force`` is for the end of a meeting, where the last window is due whether or not it
        reached either threshold — otherwise the final minute of a meeting is silently lost.
        """
        if not self._pending or (not force and not self.due()):
            return None

        window, self._pending, self._pending_words = self._pending, [], 0
        self._last_run = self._now()
        valid_t0 = {int(s.get("t0_ms") or 0) for s in window}

        delta = await self._ask_for_delta(window)
        recap = await self._ask_for_recap(window)

        changed = bool(delta)
        if changed:
            self.notes = merge(self.notes, delta, valid_t0=valid_t0)
        if recap and recap != self.recap:
            self.recap = recap
            changed = True

        if not changed:
            # Small talk. Storing a version that says nothing new would make the version
            # history useless for debugging the one that does.
            return None

        self.version = store.save_notes(self.meeting_id, {**self.notes, "recap": self.recap})
        return self.frame()

    def frame(self) -> Dict[str, Any]:
        """The `notes` frame, in the shape the card renders."""
        return {"type": "notes", "version": self.version, "recap": self.recap, **self.notes}

    async def _ask_for_delta(self, window: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            raw = await self._call(prompts.notes_messages(self.notes, window), temperature=0.2)
        except Exception:  # noqa: BLE001 — one bad window, never the meeting
            log.exception("meetingsense: notes delta failed for %s", self.meeting_id)
            return {}
        return parse_delta(raw)

    async def _ask_for_recap(self, window: Sequence[Dict[str, Any]]) -> str:
        try:
            raw = await self._call(prompts.recap_messages(self.recap, window), temperature=0.3)
        except Exception:  # noqa: BLE001
            log.exception("meetingsense: recap failed for %s", self.meeting_id)
            return ""
        if not isinstance(raw, str):
            return ""
        return cap_words(raw.strip())


def engine_factory(config: Any) -> Callable[[str], "NotesEngine"]:
    """``(meeting_id) -> NotesEngine``, configured — the one place both transports build one.

    This function is the fix for MS12's real gap: the engine shipped complete and tested and
    was **constructed by nothing**, so `start` echoed ``notes: true`` back to clients and no
    meeting ever produced a `notes` frame. Two call sites building one each would be two
    places for that to happen again, so there is one.

    Returns a factory rather than an engine because an engine holds one meeting's rolling
    state, and a connection can record more than one meeting in sequence.
    """
    notes_config = getattr(config, "notes", None)

    def build(meeting_id: str) -> "NotesEngine":
        return NotesEngine(
            meeting_id,
            call=lambda messages, **kw: call_model(
                messages, model=getattr(notes_config, "model", "") or "", **kw
            ),
            interval_s=getattr(notes_config, "interval_s", None),
            max_words=getattr(notes_config, "max_words", None),
        )

    return build


async def call_model(messages: List[Dict[str, str]], *, temperature: float = 0.2, model: str = "") -> str:
    """The default model call: the same router `jobs.py` uses.

    Imported inside the function so this module stays importable — and testable — without the
    compute stack, which is the same reason `store` reaches for `storage` lazily.
    """
    from ..compute import route_chat

    response = await route_chat(
        messages,
        temperature=temperature,
        max_tokens=600,
        model=model or None,
    )
    return ((response.get("choices") or [{}])[0].get("message", {}) or {}).get("content", "") or ""
