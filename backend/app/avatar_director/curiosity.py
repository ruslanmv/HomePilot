"""Curiosity — she remembers what you cared about, and waits for a good moment to ask.

Spec v1.1 §6.12, batch B16. The hardest thing here is not the scoring; it is the silence.
A companion who asks about your week is warm. One who asks *while you are mid-sentence*, or
during a guided meditation, or four times in an hour, is a notification with a face. So the
scheduler is written as a list of reasons not to speak, and every one of them is a test that
fails if the reason stops holding.

## Three layers, deliberately separated

* **Scoring is pure functions.** ``score_turn``, ``decay``, ``engaged`` take numbers and
  return numbers. No clock, no store, no I/O — so the arithmetic in §6.12 can be checked
  against the spec directly rather than inferred from behaviour.
* **Records live in the existing long-term memory**, as a new ``interest`` category, not in
  a parallel store. ``InterestStore`` is a thin adapter over ``app.ltm``; there is no table
  here, no migration, and forgetting a persona through the existing path forgets its
  interests with it. That last property is why this matters: a parallel store is a second
  place a user's data hides from the delete button they already have.
* **The scheduler consumes events only.** It has no timer and no thread; it is fed what the
  session already reports (``ctx``, ``user_event``) and asked whether now is a moment. A
  scheduler that woke itself would be one that could speak into a room the client has not
  described in twenty minutes.

## What is not here

The question itself. §6.12 says the persona LLM generates it, grounded on the record's
summary — so this decides *whether* and *which topic*, hands both to the caller, and does
not write a word of dialogue. Keeping generation out means the mutes cannot be bypassed by
a code path that "just" phrases something.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("avatar_director.curiosity")

#: The LTM category interest records live in. Declared in ``app.ltm.VALID_CATEGORIES``.
CATEGORY = "interest"

#: §6.12's scoring constants, named rather than inlined so a reviewer can diff them.
ENGAGED_DELTA = 0.15
DISENGAGED_DELTA = -0.10
DAILY_DECAY = 0.98

#: A topic below this is not worth asking about; it is kept, and it stops competing.
FLOOR = 0.05

#: Attention at or above this means the activity has them. §6.12's hard mute.
ATTENTION_MUTE = 0.9

#: Scenes that silence initiative entirely, whatever the budget says.
SILENT_SCENES = frozenset({"meditation"})

#: How many interest records one persona may accumulate. The LTM caps at 200 entries for
#: everything; curiosity may not spend the whole allowance on itself.
MAX_RECORDS = 40


# ── scoring: pure functions, no clock, no store ──────────────────────────────


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def engaged(reply_length: int, median_length: float, valence: float) -> bool:
    """§6.12: engaged means a reply longer than their median *and* positively toned.

    Both, not either. A long angry reply is engagement with the argument, not the topic,
    and treating it as interest is how a companion learns to keep poking a sore spot.
    """
    return reply_length > median_length and valence > 0


def score_turn(current: float, is_engaged: bool) -> float:
    """One conversational turn's effect on a topic's curiosity. Clamped to [0, 1]."""
    return clamp01(current + (ENGAGED_DELTA if is_engaged else DISENGAGED_DELTA))


def decay(current: float, days: float) -> float:
    """×0.98 per day (§6.12). Continuous in ``days`` so a gap of hours decays partially.

    A step function on whole days would make a topic touched at 23:59 and again at 00:01
    lose a full day's interest, which is the sort of arithmetic nobody notices until the
    companion has quietly forgotten something they mentioned yesterday.
    """
    if days <= 0:
        return clamp01(current)
    return clamp01(current * (DAILY_DECAY**days))


def median(values: List[float]) -> float:
    """Median reply length, for ``engaged``. Median rather than mean: one long message
    should not move the bar for every message after it."""
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


# ── the record ───────────────────────────────────────────────────────────────


@dataclass
class InterestRecord:
    """§6.12's shape. Serialised as the ``value`` of one LTM row."""

    topic: str
    summary: str = ""
    curiosity: float = 0.5
    lastTouched: str = ""
    openThread: bool = False
    sourceMsgIds: List[str] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> Optional["InterestRecord"]:
        """Read one LTM row. A row that will not parse is skipped, not fatal — the store is
        shared with everything else the persona remembers."""
        try:
            payload = json.loads(row.get("value") or "{}")
        except (TypeError, ValueError):
            log.debug("interest row %r is not JSON — skipped", row.get("key"))
            return None
        if not isinstance(payload, dict):
            return None
        known = {f for f in cls.__dataclass_fields__}
        return cls(topic=row.get("key") or payload.get("topic") or "", **{k: v for k, v in payload.items() if k in known and k != "topic"})

    def as_value(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)


# ── the store: the existing memory, one new category ─────────────────────────


class InterestStore:
    """A thin adapter over ``app.ltm``. Deliberately thin — the moment it grew a cache or a
    table of its own it would be the parallel store §6.12 rules out."""

    def __init__(self, project_id: str, *, user_id: Optional[str] = None, ltm=None) -> None:
        self.project_id = project_id
        self.user_id = user_id
        self._ltm = ltm

    @property
    def ltm(self):
        if self._ltm is None:
            from app import ltm  # noqa: PLC0415 — lazy so this module imports without sqlite work

            self._ltm = ltm
        return self._ltm

    def all(self) -> List[InterestRecord]:
        rows = self.ltm.get_memories(self.project_id, category=CATEGORY, user_id=self.user_id)
        records = [InterestRecord.from_row(row) for row in rows]
        return [r for r in records if r is not None]

    def get(self, topic: str) -> Optional[InterestRecord]:
        for record in self.all():
            if record.topic == topic:
                return record
        return None

    def save(self, record: InterestRecord) -> InterestRecord:
        self.ltm.upsert_memory(
            self.project_id,
            CATEGORY,
            record.topic,
            record.as_value(),
            confidence=max(FLOOR, record.curiosity),
            source_type="inferred",
            user_id=self.user_id,
        )
        return record

    def forget(self, topic: str) -> bool:
        return bool(self.ltm.delete_memory(self.project_id, CATEGORY, topic, user_id=self.user_id))

    def prune(self, keep: int = MAX_RECORDS) -> int:
        """Drop the least interesting records beyond the cap. Curiosity shares the persona's
        200-entry allowance with everything else it remembers and may not spend it all."""
        records = sorted(self.all(), key=lambda r: r.curiosity, reverse=True)
        dropped = 0
        for record in records[keep:]:
            if self.forget(record.topic):
                dropped += 1
        return dropped


# ── the engine: scoring a conversation into records ──────────────────────────


class CuriosityEngine:
    """Turns conversation into interest records. Holds no opinion about when to speak."""

    def __init__(self, store: InterestStore, *, now: Callable[[], float] = time.time) -> None:
        self.store = store
        self.now = now

    def _stamp(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.now()))

    def observe(
        self,
        topic: str,
        *,
        reply_length: int,
        median_length: float,
        valence: float,
        summary: str = "",
        open_thread: Optional[bool] = None,
        message_id: Optional[str] = None,
    ) -> InterestRecord:
        """One turn about one topic. Decays first, then scores — in that order, so a topic
        untouched for a month does not get a fresh +0.15 on top of a stale high score."""
        record = self.store.get(topic) or InterestRecord(topic=topic, curiosity=0.5)
        record.curiosity = decay(record.curiosity, self._days_since(record.lastTouched))
        record.curiosity = score_turn(record.curiosity, engaged(reply_length, median_length, valence))
        record.lastTouched = self._stamp()
        if summary:
            record.summary = summary
        if open_thread is not None:
            record.openThread = bool(open_thread)
        if message_id and message_id not in record.sourceMsgIds:
            # Bounded: a thread that runs for months must not grow an unbounded id list
            # inside a row that is capped at the LTM's own value size.
            record.sourceMsgIds = (record.sourceMsgIds + [message_id])[-10:]
        self.store.save(record)
        return record

    def _days_since(self, stamp: str) -> float:
        if not stamp:
            return 0.0
        try:
            when = time.mktime(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
        except (ValueError, OverflowError):
            return 0.0
        return max(0.0, (self.now() - when) / 86400.0)

    def best_open_thread(self, exclude: Optional[set] = None) -> Optional[InterestRecord]:
        """The argmax-curiosity open thread (§6.12), or None.

        ``exclude`` is how the scheduler avoids asking about the aquarium four times in one
        evening: argmax over a set that does not change between openings picks the same
        topic every time, and a companion who asks the same question at 0:15, 2:30, 7:10 and
        15:00 is the exact failure "no moment felt intrusive" is about. The twenty-minute
        replay found this; the arithmetic alone would not have.

        Ties break on the topic name, so the same state always produces the same choice.
        """
        skip = exclude or set()
        candidates = [r for r in self.store.all() if r.openThread and r.curiosity > FLOOR and r.topic not in skip]
        if not candidates:
            return None
        return sorted(candidates, key=lambda r: (-r.curiosity, r.topic))[0]


# ── the scheduler: events in, at most one opening out ────────────────────────


@dataclass
class SessionState:
    """What the scheduler knows, entirely from events the client already sends."""

    budget: int = 4
    attention: float = 0.0
    scene: Optional[str] = None
    activity: Optional[str] = None
    speaking: bool = False
    opted_out: bool = False
    last_initiative_at: Optional[float] = None
    openings: List[str] = field(default_factory=list)


class InitiativeScheduler:
    """Whether now is a moment, and about what.

    Every path through :meth:`due` that returns ``None`` names its reason, because a silence
    with no explanation is indistinguishable from a bug — and because the reasons are the
    feature. The order matters: mutes are checked before the budget, so a muted session does
    not spend budget it was never going to use.
    """

    #: Everything that silences her, in the order §6.12 lists them.
    MUTES = ("user_speaking", "attention", "scene", "opted_out")

    def __init__(self, engine: CuriosityEngine, config, *, now: Callable[[], float] = time.time) -> None:
        self.engine = engine
        self.config = config
        self.now = now
        self.state = SessionState(budget=int(getattr(config.curiosity, "session_budget", 4)))
        self.min_gap_ms = int(getattr(config.curiosity, "min_gap_ms", 90000))
        self.min_session_age_ms = int(getattr(config.curiosity, "min_session_age_ms", 120000))
        self.started_at = now()
        self.refusals: Dict[str, int] = {}
        self.fired: List[Dict[str, Any]] = []
        #: Topics already raised this session. Cleared only by a new session.
        self.asked: set = set()
        self._opening_at: Optional[float] = None
        self._opening_name = ""

    # ── events ───────────────────────────────────────────────────────────────

    def on_ctx(self, message: Dict[str, Any]) -> None:
        """A `ctx` from the client: mode, activity, attention and — from B14 — the scene."""
        attention = message.get("attention")
        if isinstance(attention, (int, float)):
            self.state.attention = float(attention)
        self.state.activity = message.get("activity")
        if "scene" in message:
            self.state.scene = message.get("scene")

    def on_user_event(self, name: str) -> None:
        """A `user_event`.

        Two independent readings of the same event, deliberately not an if/elif chain:
        `user:silent` both clears the speaking flag *and* is the companion profile's most
        common opening (`user:silent>12000`). Chained, the first reading would swallow it
        and the commonest polite moment in the whole system would never arrive.
        """
        if name == "user:speaking":
            self.state.speaking = True
        elif name == "user:silent":
            self.state.speaking = False
        elif name == "curiosity:off":
            self.state.opted_out = True
        elif name == "curiosity:on":
            self.state.opted_out = False

        if name in self.state.openings:
            self._opening_at = self.now()
            self._opening_name = name

    def set_openings(self, openings: List[str]) -> None:
        """The active profile's `commentaryOpenings`, minus any dwell suffix. §6.12 says the
        openings are the profile's, so they arrive from the client rather than living here."""
        self.state.openings = [str(o).split(">")[0] for o in openings or []]

    # ── the decision ─────────────────────────────────────────────────────────

    def muted(self) -> Optional[str]:
        """The first reason she must not speak, or None. Checked before anything else."""
        if self.state.speaking:
            return "user_speaking"
        if self.state.attention >= ATTENTION_MUTE:
            return "attention"
        if (self.state.scene or "") in SILENT_SCENES:
            return "scene"
        if self.state.opted_out:
            return "opted_out"
        return None

    def due(self, at: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """One initiative, or None with a recorded reason.

        Returns ``{topic, summary, curiosity}`` — a subject, not a sentence. §6.12 leaves the
        wording to the persona LLM, and keeping it there means no code path can phrase
        something into existence past a mute.
        """
        at = self.now() if at is None else at

        mute = self.muted()
        if mute:
            return self._refuse(mute)
        if self.state.budget <= 0:
            return self._refuse("budget")
        if (at - self.started_at) * 1000 < self.min_session_age_ms:
            # She does not greet you with a question. The twenty-minute replay opened an
            # evening fifteen seconds in with "Mum's scan results are due this week" —
            # correct by every other rule, and the exact thing "felt intrusive" means.
            return self._refuse("too_early")
        if self._opening_at is None:
            return self._refuse("no_opening")
        if self.state.last_initiative_at is not None:
            if (at - self.state.last_initiative_at) * 1000 < self.min_gap_ms:
                return self._refuse("too_soon")

        record = self.engine.best_open_thread(exclude=self.asked)
        if record is None:
            return self._refuse("nothing_to_ask")

        self.state.budget -= 1
        self.state.last_initiative_at = at
        self.asked.add(record.topic)
        # The opening is spent. Without this one opening would licence every check that
        # followed it, which is how "at a polite moment" becomes "from then on".
        opening, self._opening_at, self._opening_name = self._opening_name, None, ""
        chosen = {
            "topic": record.topic,
            "summary": record.summary,
            "curiosity": record.curiosity,
            "opening": opening,
            "at": at,
        }
        self.fired.append(chosen)
        return chosen

    def _refuse(self, why: str) -> None:
        self.refusals[why] = self.refusals.get(why, 0) + 1
        return None

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "budget": self.state.budget,
            "fired": len(self.fired),
            "refusals": dict(self.refusals),
            "muted": self.muted(),
        }
