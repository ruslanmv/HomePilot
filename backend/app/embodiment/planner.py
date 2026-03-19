"""
Embodiment Planner — converts persona intent into motion plans.

Given a user utterance and persona config, produces a MotionPlan
that the VR client can execute.
"""
from __future__ import annotations

import re
from typing import Optional

from .motion_dsl import MotionPlan, MotionPlanBuilder


# ── Intent patterns ───────────────────────────────────────────────────

_SPATIAL_PATTERNS = [
    (r"\bcome\s+here\b", "_come_here"),
    (r"\bfollow\s+me\b", "_follow_me"),
    (r"\bstop\b", "_stop"),
    (r"\bsit\s+down\b", "_sit_down"),
    (r"\bstand\s+up\b", "_stand_up"),
    (r"\blook\s+at\s+me\b", "_look_at_me"),
    (r"\btake\s+my\s+hand\b", "_take_hand"),
    (r"\bwalk\s+with\s+me\b", "_walk_with_me"),
    (r"\bstay\s+here\b", "_stay_here"),
    (r"\bcome\s+closer\b", "_come_closer"),
    (r"\bgo\s+away\b", "_go_away"),
    (r"\bwave\b", "_wave"),
    (r"\bhigh[\s-]?five\b", "_high_five"),
    (r"\bpoint\b", "_point"),
]


def plan_from_utterance(
    utterance: str,
    persona_id: str = "",
    personal_distance_m: float = 1.2,
    can_offer_hand: bool = False,
    can_high_five: bool = False,
) -> Optional[MotionPlan]:
    """Parse a user utterance for spatial commands and return a MotionPlan.

    Returns None if no spatial intent is detected.
    """
    text = utterance.lower().strip()
    builder = MotionPlanBuilder(persona_id=persona_id)

    for pattern, handler_name in _SPATIAL_PATTERNS:
        if re.search(pattern, text):
            handler = _HANDLERS.get(handler_name)
            if handler:
                return handler(
                    builder,
                    personal_distance_m=personal_distance_m,
                    can_offer_hand=can_offer_hand,
                    can_high_five=can_high_five,
                )

    return None


# ── Handlers ──────────────────────────────────────────────────────────


def _come_here(builder: MotionPlanBuilder, **kwargs) -> MotionPlan:
    dist = kwargs.get("personal_distance_m", 1.2)
    return (
        builder.approach("user", distance_m=dist)
        .look_at("user_head")
        .expression("soft_smile", weight=0.4)
        .build()
    )


def _follow_me(builder: MotionPlanBuilder, **kwargs) -> MotionPlan:
    dist = kwargs.get("personal_distance_m", 1.2)
    return builder.follow("user", distance_m=dist).look_at("user_head").build()


def _stop(builder: MotionPlanBuilder, **kwargs) -> MotionPlan:
    return builder.stop().idle("breathing").build()


def _sit_down(builder: MotionPlanBuilder, **kwargs) -> MotionPlan:
    return builder.sit("nearest_seat").look_at("user_head").build()


def _stand_up(builder: MotionPlanBuilder, **kwargs) -> MotionPlan:
    return builder.stand().look_at("user_head").build()


def _look_at_me(builder: MotionPlanBuilder, **kwargs) -> MotionPlan:
    return builder.look_at("user_head", speed=0.9).expression("attentive", weight=0.5).build()


def _take_hand(builder: MotionPlanBuilder, **kwargs) -> MotionPlan:
    if not kwargs.get("can_offer_hand"):
        return builder.look_at("user_head").expression("apologetic", weight=0.3).build()
    return (
        builder.approach("user", distance_m=0.4)
        .look_at("user_head")
        .offer_hand("right")
        .build()
    )


def _walk_with_me(builder: MotionPlanBuilder, **kwargs) -> MotionPlan:
    dist = kwargs.get("personal_distance_m", 1.2)
    return builder.follow("user", distance_m=dist).look_at("user_head").build()


def _stay_here(builder: MotionPlanBuilder, **kwargs) -> MotionPlan:
    return builder.stop().idle("breathing").look_at("user_head").build()


def _come_closer(builder: MotionPlanBuilder, **kwargs) -> MotionPlan:
    return (
        builder.approach("user", distance_m=0.5, speed=0.5)
        .look_at("user_head")
        .build()
    )


def _go_away(builder: MotionPlanBuilder, **kwargs) -> MotionPlan:
    return builder.retreat(distance_m=2.0).idle("breathing").build()


def _wave(builder: MotionPlanBuilder, **kwargs) -> MotionPlan:
    return builder.wave("right").expression("happy", weight=0.6).build()


def _high_five(builder: MotionPlanBuilder, **kwargs) -> MotionPlan:
    if not kwargs.get("can_high_five"):
        return builder.wave("right").expression("happy", weight=0.5).build()
    return (
        builder.approach("user", distance_m=0.5)
        .gesture("high_five", side="right")
        .expression("excited", weight=0.8)
        .build()
    )


def _point(builder: MotionPlanBuilder, **kwargs) -> MotionPlan:
    return builder.point("forward", side="right").build()


_HANDLERS = {
    "_come_here": _come_here,
    "_follow_me": _follow_me,
    "_stop": _stop,
    "_sit_down": _sit_down,
    "_stand_up": _stand_up,
    "_look_at_me": _look_at_me,
    "_take_hand": _take_hand,
    "_walk_with_me": _walk_with_me,
    "_stay_here": _stay_here,
    "_come_closer": _come_closer,
    "_go_away": _go_away,
    "_wave": _wave,
    "_high_five": _high_five,
    "_point": _point,
}
