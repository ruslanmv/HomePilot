"""
Policy subsystem for the interactive service.

Three layers, in order of authority:

1. Chassis guardrails (``guardrails.py``)
     Always-on safety rules enforced by the chassis itself — cannot
     be disabled via a profile YAML. E.g. mature content requires
     explicit consent, blocked-region list applies globally.

2. Policy profiles (``profiles.py``)
     Declarative per-mode rules loaded from ``profiles/*.yaml``.
     Controls which intents are allowed/blocked for an experience
     mode, soft-refuse copy, default language.

3. Decision engine (``decision.py``)
     Three explicit checkpoints the router calls:
       - check_catalog_visibility  (which actions even show up?)
       - check_action_execution     (can this action fire now?)
       - check_free_input           (is this free-text input OK?)
     Each returns a ``Decision`` with decision + reason_code.

``classifier.py`` is the NLP layer that maps free text to an
``intent_code`` — the key shared between the policy and the
intent-map runtime.
"""
from .decision import Decision, check_action_execution, check_catalog_visibility, check_free_input
from .guardrails import ChassisResult, apply_chassis_guardrails
from .profiles import PolicyProfile, load_profile, list_profiles
from .classifier import classify_intent

__all__ = [
    "Decision",
    "check_action_execution",
    "check_catalog_visibility",
    "check_free_input",
    "ChassisResult",
    "apply_chassis_guardrails",
    "PolicyProfile",
    "load_profile",
    "list_profiles",
    "classify_intent",
]
