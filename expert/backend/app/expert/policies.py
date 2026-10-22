from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Literal

from .config import (
    EXPERT_DEEP_TEMPERATURE,
    EXPERT_FAST_MAX_TOKENS,
    EXPERT_FAST_TEMPERATURE,
    EXPERT_FAST_TOOL_ROUNDS,
    EXPERT_HEAVY_MAX_TOKENS,
    EXPERT_HEAVY_RESEARCH_MIN_COMPLEXITY,
    EXPERT_HEAVY_TEMPERATURE,
    EXPERT_HEAVY_TOOL_ROUNDS,
    EXPERT_THINK_MAX_TOKENS,
    EXPERT_THINK_PLAN_MIN_COMPLEXITY,
    EXPERT_THINK_TEMPERATURE,
    EXPERT_THINK_TOOL_ROUNDS,
)


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


# ─────────────────────────────────────────────────────────────────────────────
# Effort: the mode is a ceiling; the request decides how much of it is spent
# ─────────────────────────────────────────────────────────────────────────────

EffortLevel = Literal["direct", "standard", "full"]

_GREETING = re.compile(
    r"^(hi|hello|hey|yo|hola|ciao|salve|bonjour|hallo|thanks|thank you|thx|ok|okay|test|ping|"
    r"good (morning|afternoon|evening)|how are you)\b[\s!.?,]*$",
    re.I,
)


def is_trivial(query: str) -> bool:
    """A greeting, an acknowledgement, or a few words with no question: the kind of turn that
    needs one generation whatever mode is selected (the same rule the composer uses)."""
    t = (query or "").strip()
    if not t or _GREETING.match(t):
        return True
    words = t.split()
    return len(words) <= 3 and "?" not in t and len(t) <= 24


@dataclass(frozen=True)
class EffortProfile:
    mode: str
    level: EffortLevel          # direct = one generation · standard = the mode without its optional stages · full
    temperature: float
    max_tokens: int
    tool_rounds: int
    plan: bool                  # think: analyze → plan before solving
    research: bool              # heavy: the research agent runs
    reason: str                 # one line for the trace
    analyze: bool = False       # think: a visible analysis step before the answer (always with plan)

    def as_dict(self) -> dict:
        return asdict(self)


def effort_for(mode: str, complexity: int, *, trivial: bool = False, forced_tools: bool = False) -> EffortProfile:
    """What this request may spend in ``mode``. Fast is always one generation. Expert plans
    only above a complexity threshold. Heavy researches only when the question is complex or
    the user asked for a search; a trivial message is answered directly in every mode."""
    if mode == "fast":
        return EffortProfile("fast", "direct", EXPERT_FAST_TEMPERATURE, EXPERT_FAST_MAX_TOKENS,
                             EXPERT_FAST_TOOL_ROUNDS, False, False, "one generation, tools on demand")
    if mode == "think":
        if trivial:
            return EffortProfile("think", "direct", EXPERT_THINK_TEMPERATURE, EXPERT_THINK_MAX_TOKENS,
                                 EXPERT_THINK_TOOL_ROUNDS, False, False, "a short message needs no plan")
        if complexity < EXPERT_THINK_PLAN_MIN_COMPLEXITY:
            # The reasoning stays visible: a short analysis, then the answer from it (two calls).
            return EffortProfile(
                "think", "standard", EXPERT_THINK_TEMPERATURE, EXPERT_THINK_MAX_TOKENS, EXPERT_THINK_TOOL_ROUNDS,
                False, False,
                f"complexity {complexity} is below {EXPERT_THINK_PLAN_MIN_COMPLEXITY}: analyzed, then answered without a separate plan",
                analyze=True,
            )
        return EffortProfile("think", "full", EXPERT_THINK_TEMPERATURE, EXPERT_THINK_MAX_TOKENS,
                             EXPERT_THINK_TOOL_ROUNDS, True, False, f"complexity {complexity}: analyze, plan, solve",
                             analyze=True)
    if mode == "heavy":
        if trivial:
            return EffortProfile("heavy", "direct", EXPERT_HEAVY_TEMPERATURE, EXPERT_HEAVY_MAX_TOKENS,
                                 EXPERT_HEAVY_TOOL_ROUNDS, False, False, "a short message needs no verification")
        research = forced_tools or complexity >= EXPERT_HEAVY_RESEARCH_MIN_COMPLEXITY
        if forced_tools:
            why = "a web search was asked for: research, reason, synthesize, validate"
        elif research:
            why = f"complexity {complexity}: research, reason, synthesize, validate"
        else:
            why = f"complexity {complexity} is below {EXPERT_HEAVY_RESEARCH_MIN_COMPLEXITY}: reason, synthesize, validate"
        return EffortProfile("heavy", "full" if research else "standard", EXPERT_HEAVY_TEMPERATURE,
                             EXPERT_HEAVY_MAX_TOKENS, EXPERT_HEAVY_TOOL_ROUNDS, False, research, why)
    return EffortProfile("deep", "full", EXPERT_DEEP_TEMPERATURE, EXPERT_HEAVY_MAX_TOKENS,
                         EXPERT_THINK_TOOL_ROUNDS, True, True, "deep research runs its own plan")
