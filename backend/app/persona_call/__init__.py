"""
persona_call — phone-call conversational dynamics on top of voice_call.

Adds nothing to a persona's BASE system prompt. Instead, when a persona
is on a live phone call, this module composes a small per-turn system
*suffix* that:

  * tells the persona it is currently on a phone call (not chat),
  * applies one research-grounded rule from the design doc (e.g.
    "skip 'how are you' after 9 pm local"),
  * enforces the two-phase closing handshake at the state machine level
    (the only place the model is overridden rather than advised),
  * emits server-originated *backchannels* and *fillers* on a separate
    low-volume stream so the user hears continuers + thinking sounds
    without waiting for a full LLM turn.

Fully additive + feature-flagged. With ``PERSONA_CALL_ENABLED=false``
(the default) this module is never imported and no row is ever written
to the ``persona_call_state`` table.

Published research baked in:
  Schegloff 1968, Schegloff & Sacks 1973, Sacks/Schegloff/Jefferson 1974,
  Jefferson 1984, Stivers et al. 2009, Clark & French 1981,
  Local & Walker 2012, OpenAI Realtime Prompting Guide, Sesame 2025.

Call-centre software-engineering practice applied:
  single-source-of-truth state machine; every behavior has a named
  module and a test anchor; deterministic telemetry counters for
  naturalness SLOs; zero coupling to persona storage.
"""
from __future__ import annotations

__all__ = ["config", "directive", "router"]
