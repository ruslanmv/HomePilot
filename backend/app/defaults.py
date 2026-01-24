"""
Centralized default values for HomePilot.

This file contains constants that should be used consistently across
the application. Modify these values to change behavior globally.
"""

# =============================================================================
# NEGATIVE PROMPT DEFAULTS
# =============================================================================

# Anti-duplicate terms to prevent Stable Diffusion from generating doubled subjects
ANTI_DUPLICATE_TERMS = (
    "duplicate, clone, multiple people, two heads, two faces, "
    "multiple bodies, extra limbs, split image, twin, copy"
)

# Quality-related negative terms
QUALITY_NEGATIVE_TERMS = (
    "blurry, low quality, text, watermark, ugly, deformed, disfigured, "
    "bad anatomy, worst quality, low resolution, "
    "jpeg artifacts, compression artifacts, noise, grainy"
)

# Standard negative prompt combining all terms
# Use this as the default for ALL image generation
DEFAULT_NEGATIVE_PROMPT = f"{QUALITY_NEGATIVE_TERMS}, {ANTI_DUPLICATE_TERMS}"

# Shorter version for when space is limited
DEFAULT_NEGATIVE_PROMPT_SHORT = (
    "blurry, low quality, ugly, deformed, duplicate, clone, multiple people, "
    "two heads, split image, extra limbs"
)


def enhance_negative_prompt(negative: str | None) -> str:
    """
    Ensure a negative prompt includes anti-duplicate terms.

    If the provided negative prompt is empty, weak, or missing anti-duplicate
    terms, this function will enhance it with the standard terms.

    Args:
        negative: The original negative prompt (can be None or empty)

    Returns:
        Enhanced negative prompt with anti-duplicate terms
    """
    if not negative or not negative.strip():
        return DEFAULT_NEGATIVE_PROMPT

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
        "duplicate", "clone", "multiple people", "two heads", "split image"
    ])

    if is_weak:
        # Replace weak prompt entirely
        return DEFAULT_NEGATIVE_PROMPT

    if not has_anti_duplicate:
        # Append anti-duplicate terms
        return f"{negative}, {ANTI_DUPLICATE_TERMS}"

    return negative
