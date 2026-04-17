"""
Environmental + caller-context inputs for the per-turn composer.

Three kinds of signal, all computed on demand (never stored):

  (a) Local clock — hour, day-of-week, weekend bit. Resolved from the
      caller's ``device_info.tz`` when present, else server tz, else UTC.
      Late-night brevity and morning-energy rules key off this.

  (b) Recency — weeks since this (user, persona) last spoke. Drives the
      "hey, it's been a while" one-shot acknowledgment.

  (c) Caller-state extraction from STT — a tiny regex/keyword classifier
      that runs on every user utterance:
        * mobility  (driving / walking / on transit)
        * time pressure  (quick question, running late, stepping out)
        * reason-for-call sentence  (turn ≤ 3)

All inference is local + deterministic. No LLM calls in this module.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


# ── local clock ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class CallEnv:
    local_hour: int
    day_of_week: int          # 0 Mon … 6 Sun
    is_weekend: bool
    weeks_since_last_call: int    # -1 when never
    had_unfinished_topic: bool
    resumed_from_topic: Optional[str] = None


def _resolve_tz(tz_name: Optional[str]):
    """Best-effort tz resolution. Returns a tzinfo or UTC."""
    if not tz_name:
        return _dt.timezone.utc
    try:
        # Python 3.9+ stdlib
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_name)
    except Exception:
        return _dt.timezone.utc


def compute_env(
    *,
    tz: Optional[str] = None,
    weeks_since_last_call: int = -1,
    resumed_from_topic: Optional[str] = None,
    now: Optional[_dt.datetime] = None,
) -> CallEnv:
    """Build a CallEnv from primitive inputs. No DB access here —
    ws.py does the session lookups and calls this with the results so
    this function stays cheap and unit-testable."""
    tzinfo = _resolve_tz(tz)
    current = (now or _dt.datetime.now(tz=_dt.timezone.utc)).astimezone(tzinfo)
    return CallEnv(
        local_hour=current.hour,
        day_of_week=current.weekday(),
        is_weekend=current.weekday() >= 5,
        weeks_since_last_call=weeks_since_last_call,
        had_unfinished_topic=bool(resumed_from_topic),
        resumed_from_topic=resumed_from_topic,
    )


# ── caller-state extraction ───────────────────────────────────────────

# Deliberately narrow regexes. False positives in this module produce
# a directive like "the caller is driving — keep it to one sentence",
# which is always a safe fallback; false negatives lose the rule, which
# is also safe. So tight > comprehensive.

_MOBILITY_DRIVING = re.compile(
    r"\b(i[' ]?m|i am|currently|just)?\s*(driving|behind the wheel|on the road|in the car)\b",
    re.I,
)
_MOBILITY_WALKING = re.compile(
    r"\b(i[' ]?m|i am)?\s*(walking|out on a walk|going for a walk)\b",
    re.I,
)
_MOBILITY_TRANSIT = re.compile(
    r"\b(on (the )?(train|subway|tube|metro|bus)|at the (station|airport)|boarding)\b",
    re.I,
)
_TIME_PRESSURE = re.compile(
    r"\b("
    r"quick question|only have a minute|short on time|running late|"
    r"stepping out|have to run|in a rush|in a hurry|gotta be quick"
    r")\b",
    re.I,
)

# Very loose reason-for-call cues for turn ≤ 3. We don't need to
# extract a perfect paraphrase — we just need a yes/no flag so the
# directive composer can decide whether the phase machine can move
# out of 'opening'.
#
# Intentionally does NOT match "quick question" — that is a
# time-pressure signal, not an articulated reason. The composer reads
# both signals and will still skip 'how are you' on time pressure
# alone; we just don't want to prematurely promote phase → topic
# before the skip rule fires.
_REASON_CUE = re.compile(
    r"\b("
    r"i('?m| am)?\s+calling (about|to|because|for)|"
    r"i wanted to (talk|ask|check|discuss|tell)|"
    r"the reason i('?m| am) calling|"
    r"i need (to know|help with|your help|a hand)"
    r")\b",
    re.I,
)


@dataclass
class CallerSignal:
    driving: bool = False
    walking: bool = False
    transit: bool = False
    time_pressured: bool = False
    reason_expressed: bool = False
    reason_text: str = ""

    def merge(self, other: "CallerSignal") -> "CallerSignal":
        """Accumulate across multiple user utterances in one call.
        Once a flag is set, it stays set until the phase machine
        resets it."""
        return CallerSignal(
            driving=self.driving or other.driving,
            walking=self.walking or other.walking,
            transit=self.transit or other.transit,
            time_pressured=self.time_pressured or other.time_pressured,
            reason_expressed=self.reason_expressed or other.reason_expressed,
            reason_text=self.reason_text or other.reason_text,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "driving": self.driving,
            "walking": self.walking,
            "transit": self.transit,
            "time_pressured": self.time_pressured,
            "reason_expressed": self.reason_expressed,
            "reason_text": self.reason_text,
        }

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "CallerSignal":
        d = d or {}
        return cls(
            driving=bool(d.get("driving")),
            walking=bool(d.get("walking")),
            transit=bool(d.get("transit")),
            time_pressured=bool(d.get("time_pressured")),
            reason_expressed=bool(d.get("reason_expressed")),
            reason_text=str(d.get("reason_text") or ""),
        )


def classify_utterance(text: str) -> CallerSignal:
    """Extract a CallerSignal from one user turn. O(len(text)) regex."""
    if not text:
        return CallerSignal()
    sig = CallerSignal(
        driving=bool(_MOBILITY_DRIVING.search(text)),
        walking=bool(_MOBILITY_WALKING.search(text)),
        transit=bool(_MOBILITY_TRANSIT.search(text)),
        time_pressured=bool(_TIME_PRESSURE.search(text)),
    )
    m = _REASON_CUE.search(text)
    if m:
        sig.reason_expressed = True
        # Take the remainder of the sentence as the reason paraphrase
        # — a cheap heuristic good enough for the phase machine.
        start = m.end()
        remainder = text[start:].strip()
        end = len(remainder)
        for stop in (".", "?", "!", "\n"):
            idx = remainder.find(stop)
            if idx != -1 and idx < end:
                end = idx
        sig.reason_text = remainder[:end].strip()[:140]
    return sig
