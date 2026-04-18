"""
Feature flags + runtime knobs for persona_call.

Every knob is an env var with a safe default. The module ships off.

Two flags, not one, so "shadow compose" (§ rollout P1 in the design)
can run without changing any outgoing prompt:

  PERSONA_CALL_ENABLED  — master. When false, this module is never
                          loaded into the app.
  PERSONA_CALL_APPLY    — when ENABLED=true but APPLY=false, the
                          composer runs and its output is logged to
                          ``persona_call_directives`` but NOT injected
                          as a system message. Lets us collect
                          production directives for a week before
                          letting them shape turns.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class PersonaCallConfig:
    """Resolved at every :func:`load` call — cheap, keep fresh for tests."""

    # Master flag. False = this module is not imported into main.py.
    enabled: bool
    # When True, the composed directive is actually sent to the model.
    # When False, it's logged only (shadow mode).
    apply: bool

    # Backchannel stream thresholds.
    backchannel_clause_trigger: int     # emit after N clause boundaries
    backchannel_min_gap_ms: int          # don't emit more often than this
    backchannel_volume_db: float         # played at -6 dB by default

    # Filler emission during tool/LLM wait (Stivers 700 ms trouble line).
    filler_emit_after_ms: int            # default 600

    # Phase machine thresholds.
    how_are_you_late_hour: int           # skip "how are you" at or after
    late_night_brevity_hour: int         # enter brevity bias at or after
    late_night_brevity_hour_end: int     # exit brevity bias at or before

    # Anti-repetition ledger sizes.
    ack_ledger_window: int
    opener_ledger_window: int

    # Closing handshake — the one enforced override.
    closing_trigger_tokens_extra: str    # comma-separated, user-supplied

    # Reason-for-call fallback turn.
    reason_fallback_turn: int            # at this turn, ask if nothing heard


def load() -> PersonaCallConfig:
    return PersonaCallConfig(
        enabled=_bool_env("PERSONA_CALL_ENABLED", False),
        apply=_bool_env("PERSONA_CALL_APPLY", True),
        backchannel_clause_trigger=_int_env("PERSONA_CALL_BC_CLAUSES", 2),
        backchannel_min_gap_ms=_int_env("PERSONA_CALL_BC_MIN_GAP_MS", 1800),
        backchannel_volume_db=_float_env("PERSONA_CALL_BC_VOL_DB", -6.0),
        filler_emit_after_ms=_int_env("PERSONA_CALL_FILLER_AFTER_MS", 600),
        how_are_you_late_hour=_int_env("PERSONA_CALL_HAY_LATE_HOUR", 21),
        late_night_brevity_hour=_int_env("PERSONA_CALL_LATE_HOUR", 22),
        late_night_brevity_hour_end=_int_env("PERSONA_CALL_LATE_HOUR_END", 6),
        ack_ledger_window=_int_env("PERSONA_CALL_ACK_WINDOW", 5),
        opener_ledger_window=_int_env("PERSONA_CALL_OPENER_WINDOW", 3),
        closing_trigger_tokens_extra=os.getenv(
            "PERSONA_CALL_CLOSING_EXTRA_TOKENS", ""
        ),
        reason_fallback_turn=_int_env("PERSONA_CALL_REASON_FALLBACK_TURN", 3),
    )
