"""
Personalization subsystem.

  profile.py     Read-only facade over user profile / personalization
                 signals. No writes back.
  rules.py       Rule DSL definition + validator.
  evaluator.py   evaluate(rules, state, intent) → RouterHint that
                 the interaction router consults.
"""
from .evaluator import RouterHint, evaluate
from .profile import PersonalizationProfile, resolve_profile
from .rules import Rule, RuleCondition, validate_rule

__all__ = [
    "RouterHint",
    "evaluate",
    "PersonalizationProfile",
    "resolve_profile",
    "Rule",
    "RuleCondition",
    "validate_rule",
]
