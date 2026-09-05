"""Body-doubling focus — the streak, and the arithmetic behind it (spec v1.1 §6.16, batch B22).

The client owns the pomodoro clock and the silence; this side owns the only part that has to
outlive the session. A streak the user cannot see tomorrow is not a streak, it is a counter.

## One more category, not one more store

Streaks are ``focus_streak`` rows in ``app.ltm``, alongside B16's ``interest`` rows and the
facts and preferences that were always there. Not a table, not a JSON file, not a cache: a
parallel store is a second place a user's data hides from the delete button they already
have, and forgetting a persona through the existing path must forget how many mornings they
have worked with her too.

``StreakStore`` is therefore as thin as ``InterestStore`` and for the same reason. The moment
it grows a cache it has become the thing this paragraph rules out.

## The arithmetic is pure and takes the date as an argument

:func:`advance` has no clock. A streak is entirely about *which day it is*, and a function
that reads the clock itself cannot be tested across a midnight, a timezone, or the two days
in a row that are the whole point. The caller passes ``today``; the tests pass a calendar.

Three rules, and the third is the one that makes it a streak rather than a total:

  * a second block **today** adds to ``blocks`` and leaves ``days`` alone — a streak counts
    days shown up, not work done, or a single frantic afternoon would out-rank a fortnight;
  * a block **the next day** advances ``days``;
  * a block after **a gap** resets ``days`` to 1. ``best`` is never reset, because the
    fortnight happened whether or not it is still happening.

Pure module: no FastAPI, no I/O of its own, no clock.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

log = logging.getLogger("avatar_director.focus")

#: The LTM category streak records live in. Declared in ``app.ltm.VALID_CATEGORIES``.
CATEGORY = "focus_streak"

#: Activities that may hold a streak. Closed, like the panel kinds: an open set here would
#: let a typo in a client message quietly open a new row that nothing ever reads again.
ACTIVITIES = ("focus",)

#: How many streak rows one persona may hold. A hard ceiling on a closed set is belt and
#: braces, and it is one line.
MAX_RECORDS = 8


class FocusError(Exception):
    """A refusal with a code, in the shape :mod:`panels` established."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ── the record ───────────────────────────────────────────────────────────────


@dataclass
class StreakRecord:
    """§6.16's shape. Serialised as the ``value`` of one LTM row, keyed by activity."""

    activity: str
    days: int = 0
    best: int = 0
    blocks: int = 0
    blocks_today: int = 0
    last_day: str = ""

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> Optional["StreakRecord"]:
        """Read one LTM row. A row that will not parse is skipped rather than fatal — the
        store is shared with everything else the persona remembers."""
        try:
            payload = json.loads(row.get("value") or "{}")
        except (TypeError, ValueError):
            log.debug("streak row %r is not JSON — skipped", row.get("key"))
            return None
        if not isinstance(payload, dict):
            return None
        known = {f for f in cls.__dataclass_fields__}
        return cls(
            activity=row.get("key") or payload.get("activity") or "",
            **{k: v for k, v in payload.items() if k in known and k != "activity"},
        )

    def as_value(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    @property
    def alive(self) -> bool:
        """Whether this streak is still running as of its own last day. Says nothing about
        today — that needs a date, and this property does not have one."""
        return self.days > 0


# ── the arithmetic: pure, and the date is an argument ────────────────────────


def advance(record: StreakRecord, today: date) -> StreakRecord:
    """One completed focus block, on a given day. Returns a **new** record.

    New rather than mutated so a caller cannot half-apply it: a store that raises between
    the increment and the write would otherwise leave the in-memory record ahead of the row.
    """
    last = parse_day(record.last_day)
    if last == today:
        days = record.days or 1
        blocks_today = record.blocks_today + 1
    elif last is not None and last == today - timedelta(days=1):
        days = record.days + 1
        blocks_today = 1
    else:
        # A gap, or the first block ever. Either way today is day one.
        days = 1
        blocks_today = 1

    return StreakRecord(
        activity=record.activity,
        days=days,
        # `best` is a high-water mark and is never lowered. The fortnight happened.
        best=max(record.best, days),
        blocks=record.blocks + 1,
        blocks_today=blocks_today,
        last_day=today.isoformat(),
    )


def parse_day(value: str) -> Optional[date]:
    """An ISO day, or None. Never raises: ``last_day`` comes out of a store that other code
    also writes to, so a value that will not parse is treated as "no day", not as a crash."""
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def is_live(record: StreakRecord, today: date) -> bool:
    """Is this streak still going *today*? True on the day itself and the day after.

    The day after matters: at 9am on Tuesday a Monday streak is alive and about to be
    continued. Reporting it dead until the first block lands would show the user a zero
    every morning, which is the opposite of the thing this batch is for.
    """
    last = parse_day(record.last_day)
    if last is None or record.days <= 0:
        return False
    return last in (today, today - timedelta(days=1))


def summarise(record: StreakRecord, today: date) -> Dict[str, Any]:
    """What the client is told. A dict rather than the record, because the wire shape and
    the stored shape drift for good reasons and should be free to."""
    return {
        "activity": record.activity,
        "days": record.days if is_live(record, today) else 0,
        "best": record.best,
        "blocks": record.blocks,
        "live": is_live(record, today),
    }


# ── the store: the existing memory, one new category ─────────────────────────


class StreakStore:
    """A thin adapter over ``app.ltm``, deliberately as thin as B16's ``InterestStore``."""

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

    def all(self) -> List[StreakRecord]:
        rows = self.ltm.get_memories(self.project_id, category=CATEGORY, user_id=self.user_id)
        records = [StreakRecord.from_row(row) for row in rows]
        return [r for r in records if r is not None]

    def get(self, activity: str) -> StreakRecord:
        """The record for an activity, or a fresh empty one. Never None: "you have not done
        this yet" and "zero days" are the same answer to the only question anyone asks."""
        for record in self.all():
            if record.activity == activity:
                return record
        return StreakRecord(activity=activity)

    def save(self, record: StreakRecord) -> StreakRecord:
        self.ltm.upsert_memory(
            self.project_id,
            CATEGORY,
            record.activity,
            record.as_value(),
            confidence=1.0,
            source_type="observed",
            user_id=self.user_id,
        )
        return record

    def forget(self, activity: str) -> bool:
        return bool(self.ltm.delete_memory(self.project_id, CATEGORY, activity, user_id=self.user_id))

    def record_block(self, activity: str, today: date) -> StreakRecord:
        """One completed block. The only write path, so the arithmetic cannot be bypassed."""
        if activity not in ACTIVITIES:
            raise FocusError("activity_unknown", f"{activity!r} is not a streak activity")
        return self.save(advance(self.get(activity), today))

    def recall(self, activity: str, today: date) -> Dict[str, Any]:
        """What she knows about your streak at the start of a session. §6.16's "the first
        place the user sees her memory"."""
        return summarise(self.get(activity), today)


__all__ = [
    "ACTIVITIES",
    "CATEGORY",
    "FocusError",
    "MAX_RECORDS",
    "StreakRecord",
    "StreakStore",
    "advance",
    "is_live",
    "parse_day",
    "summarise",
]
