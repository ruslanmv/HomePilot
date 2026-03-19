"""
Motion DSL — safe intermediate format for VR avatar commands.

The backend decides intent; the VR client executes the motion.
This module defines the command types and a builder for constructing
motion command sequences.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class CommandType(str, Enum):
    """All supported motion command types."""

    APPROACH = "approach"
    RETREAT = "retreat"
    MOVE_TO = "move_to"
    FOLLOW = "follow"
    STOP_FOLLOW = "stop_follow"
    STOP = "stop"
    LOOK_AT = "look_at"
    AVERT_GAZE = "avert_gaze"
    EXPRESSION = "expression"
    GESTURE = "gesture"
    POSTURE = "posture"
    SIT = "sit"
    STAND = "stand"
    WAVE = "wave"
    NOD = "nod"
    POINT = "point"
    OFFER_HAND = "offer_hand"
    ACCEPT_HAND = "accept_hand"
    HIGH_FIVE = "high_five"
    IDLE = "idle"
    SPEAK_START = "speak_start"
    SPEAK_END = "speak_end"


@dataclass
class MotionCommand:
    """A single motion command in the DSL."""

    type: str
    target: Optional[str] = None
    distance_m: Optional[float] = None
    speed: Optional[float] = None
    name: Optional[str] = None
    weight: Optional[float] = None
    side: Optional[str] = None
    position: Optional[List[float]] = None
    duration_s: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class MotionPlan:
    """A sequence of motion commands to be executed by the VR client."""

    persona_id: str = ""
    commands: List[MotionCommand] = field(default_factory=list)
    interruptible: bool = True
    priority: str = "normal"  # "low", "normal", "high", "critical"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "persona_id": self.persona_id,
            "commands": [c.to_dict() for c in self.commands],
            "interruptible": self.interruptible,
            "priority": self.priority,
        }


class MotionPlanBuilder:
    """Fluent builder for constructing MotionPlans."""

    def __init__(self, persona_id: str = "") -> None:
        self._plan = MotionPlan(persona_id=persona_id)

    def approach(
        self,
        target: str = "user",
        distance_m: float = 1.2,
        speed: float = 1.0,
    ) -> "MotionPlanBuilder":
        self._plan.commands.append(
            MotionCommand(
                type=CommandType.APPROACH,
                target=target,
                distance_m=distance_m,
                speed=speed,
            )
        )
        return self

    def retreat(self, distance_m: float = 0.5) -> "MotionPlanBuilder":
        self._plan.commands.append(
            MotionCommand(type=CommandType.RETREAT, distance_m=distance_m)
        )
        return self

    def look_at(
        self, target: str = "user_head", speed: float = 0.7
    ) -> "MotionPlanBuilder":
        self._plan.commands.append(
            MotionCommand(type=CommandType.LOOK_AT, target=target, speed=speed)
        )
        return self

    def expression(
        self, name: str = "neutral", weight: float = 0.5
    ) -> "MotionPlanBuilder":
        self._plan.commands.append(
            MotionCommand(type=CommandType.EXPRESSION, name=name, weight=weight)
        )
        return self

    def gesture(
        self, name: str, side: str = "right"
    ) -> "MotionPlanBuilder":
        self._plan.commands.append(
            MotionCommand(type=CommandType.GESTURE, name=name, side=side)
        )
        return self

    def follow(
        self, target: str = "user", distance_m: float = 1.5
    ) -> "MotionPlanBuilder":
        self._plan.commands.append(
            MotionCommand(
                type=CommandType.FOLLOW, target=target, distance_m=distance_m
            )
        )
        return self

    def stop(self) -> "MotionPlanBuilder":
        self._plan.commands.append(MotionCommand(type=CommandType.STOP))
        return self

    def sit(self, target: str = "nearest_seat") -> "MotionPlanBuilder":
        self._plan.commands.append(
            MotionCommand(type=CommandType.SIT, target=target)
        )
        return self

    def stand(self) -> "MotionPlanBuilder":
        self._plan.commands.append(MotionCommand(type=CommandType.STAND))
        return self

    def wave(self, side: str = "right") -> "MotionPlanBuilder":
        self._plan.commands.append(
            MotionCommand(type=CommandType.WAVE, side=side)
        )
        return self

    def nod(self) -> "MotionPlanBuilder":
        self._plan.commands.append(MotionCommand(type=CommandType.NOD))
        return self

    def point(
        self, target: str, side: str = "right"
    ) -> "MotionPlanBuilder":
        self._plan.commands.append(
            MotionCommand(type=CommandType.POINT, target=target, side=side)
        )
        return self

    def offer_hand(self, side: str = "right") -> "MotionPlanBuilder":
        self._plan.commands.append(
            MotionCommand(type=CommandType.OFFER_HAND, side=side)
        )
        return self

    def idle(self, name: str = "breathing") -> "MotionPlanBuilder":
        self._plan.commands.append(
            MotionCommand(type=CommandType.IDLE, name=name)
        )
        return self

    def priority(self, level: str) -> "MotionPlanBuilder":
        self._plan.priority = level
        return self

    def not_interruptible(self) -> "MotionPlanBuilder":
        self._plan.interruptible = False
        return self

    def build(self) -> MotionPlan:
        return self._plan
