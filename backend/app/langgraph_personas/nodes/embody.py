"""
Embody Node — translates intent into a motion plan for the VR client.

AAA pattern: "Animation Controller" — takes a high-level spatial intent
and produces a concrete MotionPlan using the existing embodiment planner.
The motion plan is serialized and attached to the response as x_directives.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..state import PersonaAgentState, MotionPlanDict

logger = logging.getLogger(__name__)


async def embody(state: PersonaAgentState) -> Dict[str, Any]:
    """
    Convert spatial intent into a MotionPlan dict.

    Uses the existing embodiment planner (plan_from_utterance) for
    regex-matched commands, and falls back to the spatial_intent
    hint from the think node for LLM-detected intents.
    """
    from ...embodiment.planner import plan_from_utterance

    persona_id = state.get("persona_id", "")
    user_message = state.get("user_message", "")
    personal_distance = state.get("personal_distance_m", 1.2)
    can_offer_hand = state.get("can_offer_hand", False)
    can_high_five = state.get("can_high_five", False)

    # Try the regex-based planner first (handles explicit commands)
    plan = plan_from_utterance(
        utterance=user_message,
        persona_id=persona_id,
        personal_distance_m=personal_distance,
        can_offer_hand=can_offer_hand,
        can_high_five=can_high_five,
    )

    # If regex didn't match, try the LLM-detected spatial intent
    if plan is None:
        spatial_intent = state.get("_spatial_intent", "")
        if spatial_intent:
            plan = _plan_from_intent(
                intent=spatial_intent,
                persona_id=persona_id,
                personal_distance=personal_distance,
                can_offer_hand=can_offer_hand,
                can_high_five=can_high_five,
            )

    if plan is None:
        logger.debug("[embody] no motion plan generated")
        return {}

    motion_dict: MotionPlanDict = plan.to_dict()
    logger.debug("[embody] motion plan: %d commands", len(motion_dict.get("commands", [])))

    return {
        "motion_plan": motion_dict,
    }


def _plan_from_intent(
    intent: str,
    persona_id: str,
    personal_distance: float,
    can_offer_hand: bool,
    can_high_five: bool,
) -> Optional[Any]:
    """Build a motion plan from a think-node spatial intent string."""
    from ...embodiment.motion_dsl import MotionPlanBuilder

    b = MotionPlanBuilder(persona_id=persona_id)

    intent_map = {
        "come_here": lambda: b.approach("user", distance_m=personal_distance)
                              .look_at("user_head")
                              .expression("soft_smile", weight=0.4)
                              .build(),
        "follow": lambda: b.follow("user", distance_m=personal_distance)
                           .look_at("user_head")
                           .build(),
        "sit": lambda: b.sit("nearest_seat").look_at("user_head").build(),
        "stand": lambda: b.stand().look_at("user_head").build(),
        "wave": lambda: b.wave("right").expression("happy", weight=0.6).build(),
        "approach": lambda: b.approach("user", distance_m=personal_distance)
                             .look_at("user_head")
                             .build(),
        "retreat": lambda: b.retreat(distance_m=2.0).idle("breathing").build(),
        "look_at": lambda: b.look_at("user_head", speed=0.9)
                            .expression("attentive", weight=0.5)
                            .build(),
        "offer_hand": lambda: (
            b.approach("user", distance_m=0.4).offer_hand("right").build()
            if can_offer_hand
            else b.look_at("user_head").expression("apologetic", weight=0.3).build()
        ),
        "high_five": lambda: (
            b.approach("user", distance_m=0.5).gesture("high_five", side="right")
             .expression("excited", weight=0.8).build()
            if can_high_five
            else b.wave("right").expression("happy", weight=0.5).build()
        ),
    }

    builder_fn = intent_map.get(intent)
    if builder_fn:
        return builder_fn()
    return None
