"""Keeping up with a meeting, or saying so (batch LS6).

A model that loads is not a model that works. Certification here is *"can it keep up with a
meeting"*, not *"can it technically load"* — those are different machines and only one of them is
usable.

Three decisions live in this file.

**When to warm.** When the Meeting panel opens, or when HomePilot is otherwise idle. Never on the
first spoken word — that is a cold load in front of people — and never during application startup,
which spends a user's first impression on a feature they may not open today.

**What "behind" means.** A real-time factor at or above the threshold, or a p95 final-line latency
past the "catching up" line the UI already draws. Measured over a window, because one slow
utterance is a hiccup and four in a row is a machine that cannot do this.

**What to offer when it cannot.** A **lighter local model** first. Remote is offered only if the
user had already enabled it, and only as a question. The default answer to "your computer is
slow" is never "so let us send your meeting somewhere else" — that is the one thing the person
chose this feature to avoid, and it must not be reachable by degradation.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from .benchmark import KEEPS_UP_RTF, Profile
from .manifest import PACKS_BY_ID
from .models import PREFERENCE

#: Utterances kept when judging whether the machine is behind. Small enough to react inside a
#: meeting, large enough that one slow line is not a verdict.
WINDOW = 8

#: How many of that window must be late before the machine is called behind.
BEHIND_AT = 4

#: Seconds after an utterance ends by which its final line should be on screen.
LATENCY_BUDGET_S = 2.5

#: When to warm. Named rather than inlined so the two forbidden moments stay visible.
WARM_ON = ("meeting-panel-opened", "idle")
NEVER_WARM_ON = ("first-utterance", "app-startup")


@dataclass
class Observation:
    """One utterance, measured."""

    audio_s: float
    latency_s: float

    @property
    def rtf(self) -> float:
        return self.latency_s / self.audio_s if self.audio_s > 0 else 0.0

    @property
    def late(self) -> bool:
        return self.latency_s > LATENCY_BUDGET_S or self.rtf > KEEPS_UP_RTF


@dataclass
class Offer:
    """What to propose when the machine is behind."""

    kind: str  # "lighter-local" | "ask-remote" | "none"
    pack: Optional[str] = None
    label: str = ""
    #: True when this needs the user to answer before anything changes. Remote always does.
    asks: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "pack": self.pack, "label": self.label, "asks": self.asks}


def lighter_than(pack_id: str, *, installed: Optional[List[str]] = None) -> Optional[str]:
    """The next pack down that is actually on disk, or ``None``.

    Down the *preference* order, which is roughly size order, and only among packs already
    installed — offering a lighter model that would have to be downloaded is offering a download
    in the middle of a meeting, which is the thing LS3 removed.
    """
    order = list(PREFERENCE)
    if pack_id not in order:
        return None
    have = set(installed or [])
    for candidate in order[order.index(pack_id) + 1:]:
        if candidate in have:
            return candidate
    return None


class KeepUp:
    """Watches utterance latencies and says whether the machine is keeping up."""

    def __init__(self, *, window: int = WINDOW, behind_at: int = BEHIND_AT) -> None:
        self.window = window
        self.behind_at = behind_at
        self.seen: Deque[Observation] = deque(maxlen=window)

    def record(self, *, audio_s: float, latency_s: float) -> Observation:
        observation = Observation(audio_s=audio_s, latency_s=latency_s)
        self.seen.append(observation)
        return observation

    @property
    def late_count(self) -> int:
        return sum(1 for observation in self.seen if observation.late)

    @property
    def behind(self) -> bool:
        """One slow utterance is a hiccup; four in a window is a machine that cannot do this."""
        return self.late_count >= self.behind_at

    def p95_latency_s(self) -> float:
        if not self.seen:
            return 0.0
        ordered = sorted(observation.latency_s for observation in self.seen)
        index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
        return round(ordered[index], 3)

    def stats(self) -> Dict[str, Any]:
        return {
            "observed": len(self.seen),
            "late": self.late_count,
            "behind": self.behind,
            "p95_latency_s": self.p95_latency_s(),
            "budget_s": LATENCY_BUDGET_S,
        }


def offer(
    *,
    current_pack: Optional[str],
    installed: Optional[List[str]] = None,
    remote_enabled: bool = False,
) -> Offer:
    """What to propose to somebody whose machine is behind.

    Order is the batch: lighter local first, always. Remote only if they had already turned it
    on, and then only as a question — never as a fallback that happens to them.
    """
    lighter = lighter_than(current_pack or "", installed=installed)
    if lighter:
        pack = PACKS_BY_ID.get(lighter)
        return Offer(
            kind="lighter-local",
            pack=lighter,
            label=f"Switch to {pack.label if pack else lighter} — still on this computer",
            asks=True,
        )
    if remote_enabled:
        return Offer(
            kind="ask-remote",
            label="Use the remote transcription you enabled, for this meeting?",
            asks=True,
        )
    # Nothing to offer is a legitimate answer, and much better than reaching for the cloud on
    # behalf of somebody who never asked for it.
    return Offer(kind="none", label="Transcription is running behind on this machine.")


def certify(profile: Optional[Profile]) -> Dict[str, Any]:
    """Whether a machine is certified, and on what evidence."""
    if profile is None:
        return {"certified": False, "reason": "not-benchmarked"}
    if profile.error:
        return {"certified": False, "reason": profile.error}
    return {
        "certified": profile.keeps_up,
        "reason": "ok" if profile.keeps_up else "too-slow",
        "rtf": profile.rtf,
        "threshold": KEEPS_UP_RTF,
        "device": profile.device,
    }
