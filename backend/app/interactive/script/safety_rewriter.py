"""
Safety rewriter — keeps generated text inside the active policy profile.

Phase 1 implementation: deterministic redaction + soft-rewrite for
flagged substrings. LLM phase will call an instructed rewriter
behind the same ``rewrite_for_safety`` signature.

Used by:
  - script.generator after narration is written, to catch drift
  - runtime (batch 6) free-input echo path
  - publish (batch 8) pre-publish lint
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

from ..policy.profiles import PolicyProfile


@dataclass(frozen=True)
class RewriteResult:
    """Outcome of a safety rewrite pass."""

    text: str
    changed: bool
    removed_terms: List[str]
    hints: List[str]  # human-readable diagnostics (debugging aid)


# Fixed substitution list for universally-problematic tokens.
# These always redact regardless of profile.
_UNIVERSAL_REDACT: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(child|minor|under\s*1[0-7])\b", re.I), "[redacted-age]"),
    (re.compile(r"\b(kill|stab|rape)\b", re.I), "[redacted-violence]"),
]


def rewrite_for_safety(
    text: str, profile: PolicyProfile,
) -> RewriteResult:
    """Apply universal redactions + profile-specific softening."""
    if not text:
        return RewriteResult(text="", changed=False, removed_terms=[], hints=[])

    out = text
    removed: List[str] = []

    for pattern, replacement in _UNIVERSAL_REDACT:
        new = pattern.sub(replacement, out)
        if new != out:
            removed.append(pattern.pattern)
            out = new

    # Profile-specific: if the profile's allowed list is narrow,
    # strip any explicit language that slipped in.
    if profile.allowed_intents and "explicit_request" not in profile.allowed_intents:
        explicit = re.compile(
            r"\b(pussy|cock|dick|nude|naked)\b", re.I,
        )
        new = explicit.sub("[redacted-explicit]", out)
        if new != out:
            removed.append("explicit_out_of_profile")
            out = new

    hints: List[str] = []
    if removed:
        hints.append(f"rewrote {len(removed)} problematic pattern(s)")

    return RewriteResult(
        text=out,
        changed=out != text,
        removed_terms=removed,
        hints=hints,
    )
