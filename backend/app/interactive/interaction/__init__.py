"""
Runtime interaction engine — the layer that drives the viewer turn.

Submodules:

  types.py     ActionResult + Transition + session-scoped enums.
  state.py     Per-session state machine (current_node_id,
               character mood, cumulative progress).
  router.py    resolve_next(session, action) — the core function
               called on every viewer action. Applies policy,
               progression, character-state updates, and returns
               the next payload.
  cooldown.py  Per-action cooldown tracking per session.

Every function here is pure-ish: given a session snapshot +
action, returns what should happen next. Persistence is done by
callers (the router module in batch 7) so the runtime is easy to
unit-test without SQLite writes on the hot path.
"""
from .cooldown import CooldownTracker, check_cooldown, mark_used
from .router import ActionPayload, ResolvedTurn, resolve_next
from .state import RuntimeState, build_runtime_state
from .types import Transition, TransitionKind

__all__ = [
    "CooldownTracker",
    "check_cooldown",
    "mark_used",
    "ActionPayload",
    "ResolvedTurn",
    "resolve_next",
    "RuntimeState",
    "build_runtime_state",
    "Transition",
    "TransitionKind",
]
