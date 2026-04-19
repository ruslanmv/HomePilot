"""
Progression subsystem — schemes + rewards + unlocks.

Abstracts over "level/XP" vs "mastery %" vs "CEFR tier" vs
"certification status" so one runtime handles all experience
modes without branching Python logic per mode.

Submodules:

  levels.py    Map (scheme, metric_value) → human-readable level
               + next-threshold calculation.
  rewards.py   apply_rewards(scheme, state, action) → updated
               progress dict. Handles xp_award + repeat_penalty.
  unlocks.py   is_action_unlocked(action, state) — gate check for
               catalog visibility and execution.
"""
from .levels import LevelDescription, describe_level, level_from_xp
from .rewards import RewardOutcome, apply_rewards
from .unlocks import is_action_unlocked

__all__ = [
    "LevelDescription",
    "describe_level",
    "level_from_xp",
    "RewardOutcome",
    "apply_rewards",
    "is_action_unlocked",
]
