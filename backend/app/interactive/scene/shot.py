"""
Primitive shot-spec dataclass + per-node shot selector.

A ``ShotSpec`` is what the asset layer (batch 5's assets/avatar.py)
turns into a generation prompt + duration budget. Phase 1 uses a
rule-based picker; phase 2 swaps to an LLM prompt generator behind
the same ``select_shot`` signature.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class ShotSpec:
    camera: str = "medium"          # wide | medium | close | over_shoulder
    move: str = "static"            # static | dolly_in | dolly_out | pan | orbit
    mood: str = "neutral"           # neutral | warm | suspense | playful | dramatic
    lighting: str = "natural"       # natural | soft | high_contrast | low_key
    duration_sec: int = 5
    transition: str = "cut"         # cut | crossfade | wipe
    overlays: tuple = ()            # ordered overlays (e.g. ('title_card',))


def _mood_for_mode(mode: str) -> str:
    if mode == "mature_gated":
        return "playful"
    if mode == "social_romantic":
        return "warm"
    if mode == "sfw_education":
        return "neutral"
    if mode == "language_learning":
        return "warm"
    if mode == "enterprise_training":
        return "neutral"
    return "neutral"


def select_shot(node_kind: str, *, mode: str, duration_sec: int = 5) -> ShotSpec:
    """Choose a shot spec for a node. Deterministic."""
    base_mood = _mood_for_mode(mode)
    if node_kind == "decision":
        return ShotSpec(camera="medium", move="static", mood=base_mood,
                        lighting="soft", duration_sec=max(4, duration_sec),
                        transition="cut", overlays=("choice_cta",))
    if node_kind == "ending":
        return ShotSpec(camera="wide", move="dolly_out", mood=base_mood,
                        lighting="warm", duration_sec=max(4, duration_sec),
                        transition="crossfade", overlays=("end_card",))
    if node_kind == "assessment":
        return ShotSpec(camera="close", move="static", mood="neutral",
                        lighting="soft", duration_sec=max(4, duration_sec),
                        transition="cut", overlays=("quiz_prompt",))
    if node_kind == "remediation":
        return ShotSpec(camera="medium", move="dolly_in", mood="neutral",
                        lighting="soft", duration_sec=max(5, duration_sec),
                        transition="cut", overlays=("hint_banner",))
    # default — scene / merge
    return ShotSpec(camera="medium", move="static", mood=base_mood,
                    lighting="natural", duration_sec=duration_sec,
                    transition="cut")


def to_dict(spec: ShotSpec) -> Dict[str, Any]:
    return {
        "camera": spec.camera,
        "move": spec.move,
        "mood": spec.mood,
        "lighting": spec.lighting,
        "duration_sec": spec.duration_sec,
        "transition": spec.transition,
        "overlays": list(spec.overlays),
    }
