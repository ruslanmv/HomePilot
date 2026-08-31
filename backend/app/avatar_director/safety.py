"""Tool → HomePilot safety level (spec v1.1 §6.14).

HomePilot already has a three-level safety model: *read-only*, *confirm*, *autonomous*.
The avatar tools map onto it rather than inventing a fourth thing, and the mapping lives in
one table so an audit is a table read rather than a code review.

The interesting line is the last one. Playing an animation is *autonomous* — it is low-risk
output, and asking permission before every gesture would make her unusable. Anything that
touches a camera or a screen is *confirm* **and** additionally requires the client's own
consent state to be live, because a server-side approval is not the same thing as the user
having opted in on the device holding the camera.

Pure module: no FastAPI, no I/O. It is a decision table and it should read like one.
"""

from __future__ import annotations

from typing import Dict, Literal

SafetyLevel = Literal["read-only", "confirm", "autonomous"]

#: §6.14. Anything absent is *confirm*, because the safe default for an unknown tool is to
#: ask rather than to act.
TOOL_SAFETY: Dict[str, SafetyLevel] = {
    "search_animations": "read-only",
    "get_animation": "read-only",
    "play_animation": "autonomous",
    "queue_sequence": "autonomous",
    "set_mood": "autonomous",
    "set_scene": "autonomous",
    "vision_insight": "confirm",
    "start_capture": "confirm",
    "stop_capture": "confirm",
}

#: Tools that need more than a safety level: the client must be actively sharing.
REQUIRES_CLIENT_CONSENT = frozenset({"vision_insight", "start_capture", "stop_capture"})

DEFAULT_LEVEL: SafetyLevel = "confirm"


def level_for(tool: str) -> SafetyLevel:
    """The safety level for a tool name. Unknown tools are gated, never waved through."""
    return TOOL_SAFETY.get(tool, DEFAULT_LEVEL)


def requires_consent(tool: str) -> bool:
    """Does this tool additionally need the client's capture consent to be live?"""
    return tool in REQUIRES_CLIENT_CONSENT


def is_allowed(tool: str, *, confirmed: bool = False, client_consent: bool = False) -> bool:
    """Whether a call may proceed given what the caller has established.

    A *confirm* tool needs a confirmation. A capture tool needs the client's consent as
    well — a server-side yes cannot stand in for the user opting in on the device.
    """
    if requires_consent(tool) and not client_consent:
        return False
    level = level_for(tool)
    if level == "confirm":
        return confirmed
    return True
