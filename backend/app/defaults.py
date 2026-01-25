"""
Centralized default values for HomePilot.

This file contains constants that should be used consistently across
the application. Modify these values to change behavior globally.
"""

import re

# =============================================================================
# NEGATIVE PROMPT DEFAULTS
# =============================================================================

# Anti-duplicate terms for SOLO/single-person scenes
# Prevents Stable Diffusion from generating doubled/cloned subjects
ANTI_DUPLICATE_TERMS_SOLO = (
    "multiple people, two heads, fused face, split view, collage"
)

# Anti-duplicate terms for GROUP/multi-person scenes (couples, groups)
# Does NOT include "multiple people" since that's intentional
ANTI_DUPLICATE_TERMS_GROUP = (
    "fused face, merged bodies, conjoined, split view, collage"
)

# Default uses solo terms (backwards compatible)
ANTI_DUPLICATE_TERMS = ANTI_DUPLICATE_TERMS_SOLO

# Quality-related negative terms.
# Optimized: Removed redundant synonyms (grainy, noise, ugly) to save tokens.
QUALITY_NEGATIVE_TERMS = (
    "blurry, low quality, worst quality, text, watermark, "
    "bad anatomy, jpeg artifacts"
)

# Standard negative prompt combining all terms
# Use this as the default for ALL image generation
DEFAULT_NEGATIVE_PROMPT = f"{QUALITY_NEGATIVE_TERMS}, {ANTI_DUPLICATE_TERMS}"

# Shorter version for when space is limited
DEFAULT_NEGATIVE_PROMPT_SHORT = (
    "blurry, low quality, bad anatomy, multiple people, two heads, split view"
)

# Patterns that indicate multi-person scenes
MULTI_PERSON_PATTERNS = re.compile(
    r'\b(couple|couples|two people|two persons|pair|partners|'
    r'duo|lovers|embracing each other|together|group|crowd|'
    r'2girls|2boys|2women|2men|multiple characters)\b',
    re.IGNORECASE
)


def enhance_negative_prompt(negative: str | None, positive_prompt: str | None = None) -> str:
    """
    Ensure a negative prompt includes anti-duplicate terms.

    If the provided negative prompt is empty, weak, or missing anti-duplicate
    terms, this function will enhance it with the standard terms.

    Args:
        negative: The original negative prompt (can be None or empty)
        positive_prompt: The positive prompt (used to detect multi-person scenes)

    Returns:
        Enhanced negative prompt with appropriate anti-duplicate terms
    """
    # Detect if this is a multi-person scene from the positive prompt
    is_multi_person = False
    if positive_prompt:
        is_multi_person = bool(MULTI_PERSON_PATTERNS.search(positive_prompt))

    # Choose appropriate anti-duplicate terms
    anti_dup_terms = ANTI_DUPLICATE_TERMS_GROUP if is_multi_person else ANTI_DUPLICATE_TERMS_SOLO
    quality_and_anti_dup = f"{QUALITY_NEGATIVE_TERMS}, {anti_dup_terms}"

    if not negative or not negative.strip():
        return quality_and_anti_dup

    negative_lower = negative.lower()

    # Check if it's a weak/generic negative prompt from LLM
    weak_patterns = [
        "avoid blurry",
        "avoid low",
        "no blurry",
        "without blur",
    ]
    is_weak = any(pattern in negative_lower for pattern in weak_patterns)

    # Check if anti-duplicate terms are already present
    has_anti_duplicate = any(term in negative_lower for term in [
        "two heads", "split view", "fused face", "merged bodies"
    ])

    if is_weak:
        # Replace weak prompt entirely
        return quality_and_anti_dup

    if not has_anti_duplicate:
        # Append anti-duplicate terms
        return f"{negative}, {anti_dup_terms}"

    # For multi-person scenes, remove "multiple people" from the negative if present
    if is_multi_person and "multiple people" in negative_lower:
        # Remove "multiple people" from the negative prompt
        negative = re.sub(r',?\s*multiple people\s*,?', ', ', negative, flags=re.IGNORECASE)
        negative = re.sub(r'\s+', ' ', negative).strip(' ,')

    return negative
