from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ThinkingMode = Literal["auto", "fast", "think", "heavy"]


@dataclass(frozen=True)
class ModeResolution:
    mode_used: ThinkingMode
    strategy: Literal["single-pass", "expert-thinking", "heavy-multi-pass"]


def resolve_thinking_mode(mode: ThinkingMode, complexity: int) -> ModeResolution:
    """Deterministically resolve auto/explicit mode into concrete pipeline strategy."""
    if mode == "auto":
        if complexity >= 8:
            mode = "heavy"
        elif complexity >= 5:
            mode = "think"
        else:
            mode = "fast"

    strategy = {
        "fast": "single-pass",
        "think": "expert-thinking",
        "heavy": "heavy-multi-pass",
    }[mode]

    return ModeResolution(mode_used=mode, strategy=strategy)
