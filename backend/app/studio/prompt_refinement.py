"""
Prompt Refinement Engine for Studio.

Automatically rewrites user prompts to ensure:
1. Content stays within policy boundaries
2. Output quality is literary, not crude
3. Safety constraints are embedded in the prompt itself

This is the "HOW WELL" layer - policy decides IF, this decides QUALITY.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from .models import ContentRating


class RefinementResult(BaseModel):
    """Result of prompt refinement."""
    original: str
    refined: str
    applied_rules: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    blocked: bool = False
    block_reason: Optional[str] = None


# ============================================================================
# REFINEMENT RULES
# ============================================================================

# Words/phrases to soften or replace in mature content
MATURE_SOFTENING_RULES: Dict[str, str] = {
    # Crude → Literary
    r"\bfuck(ing|ed)?\b": "intimate moment",
    r"\bsex\b": "intimacy",
    r"\bhaving sex\b": "sharing intimacy",
    r"\bmake love\b": "share a moment of closeness",
    r"\bhorny\b": "filled with desire",
    r"\bturn(ed|s)? (me |him |her )?on\b": "awakened desire",
    r"\bsexy\b": "alluring",
    r"\bhot\b(?=\s+(body|girl|guy|woman|man))": "attractive",
    r"\bnaked\b": "unclothed",
    r"\bnude\b": "bare",

    # Explicit → Implied
    r"\bstrip(ped|ping)?\b": "undressed",
    r"\bkiss(ed|ing)? (passionately|deeply)\b": "shared a lingering kiss",
    r"\btouch(ed|ing)? (intimately|sexually)\b": "caressed gently",

    # Body parts → Euphemisms (for requests, not descriptions)
    r"\bbreasts?\b": "curves",
    r"\bbutt\b": "figure",
    r"\bass\b(?!\w)": "figure",
}

# Phrases that trigger "fade to black" insertion
FADE_TO_BLACK_TRIGGERS = [
    r"they (went to|headed to|moved to) (the )?(bed|bedroom)",
    r"(clothes|clothing) (came off|fell away|were removed)",
    r"(undress|undressing|undressed)",
    r"(begin|began|started) (to )?(make love|be intimate)",
    r"(the night|evening) (continued|progressed|unfolded)",
]

# Absolute blocks even after refinement (these can't be softened safely)
UNREFINABLE_PATTERNS = [
    r"\bchild\b.*\b(sex|nude|naked|intimate)\b",
    r"\bminor\b.*\b(sex|nude|naked|intimate)\b",
    r"\b(force|forced|forcing)\b.*\b(sex|intimate|himself|herself)\b",
    r"\brape\b",
    r"\bincest\b",
    r"\bunder\s*age\b",
    r"\b(non-?consensual|without consent)\b",
]

# Enhancement suggestions for better literary quality
LITERARY_ENHANCEMENTS = [
    ("desire", "Add sensory details: lighting, temperature, atmosphere"),
    ("tension", "Build anticipation through pauses and meaningful glances"),
    ("intimacy", "Focus on emotional connection, not physical mechanics"),
    ("attraction", "Show through behavior and reaction, not description"),
]


def _apply_softening(text: str, rules: Dict[str, str]) -> Tuple[str, List[str]]:
    """Apply softening rules to text, return refined text and list of applied rules."""
    result = text
    applied = []

    for pattern, replacement in rules.items():
        if re.search(pattern, result, re.IGNORECASE):
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
            applied.append(f"Softened: {pattern[:30]}... → {replacement}")

    return result, applied


def _check_unrefinable(text: str) -> Optional[str]:
    """Check for content that cannot be refined safely."""
    for pattern in UNREFINABLE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return f"Content cannot be refined: matches safety block pattern"
    return None


def _add_fade_to_black(text: str) -> Tuple[str, bool]:
    """Check if fade-to-black guidance should be added."""
    for pattern in FADE_TO_BLACK_TRIGGERS:
        if re.search(pattern, text, re.IGNORECASE):
            return text, True
    return text, False


def _add_adult_affirmation(text: str) -> str:
    """Ensure the prompt affirms adult characters."""
    adult_patterns = [
        r"\badult\b",
        r"\b18\+\b",
        r"\bof age\b",
        r"\bgrown\b",
        r"\bmature (characters?|protagonists?|couple)\b",
    ]

    has_adult_affirmation = any(
        re.search(p, text, re.IGNORECASE) for p in adult_patterns
    )

    if not has_adult_affirmation:
        return f"[All characters are consenting adults (18+)] {text}"

    return text


def refine_prompt(
    prompt: str,
    content_rating: ContentRating,
    apply_softening: bool = True,
    add_constraints: bool = True,
) -> RefinementResult:
    """
    Refine a user prompt for safer, higher-quality generation.

    Args:
        prompt: Original user prompt
        content_rating: sfw or mature
        apply_softening: Whether to apply word softening rules
        add_constraints: Whether to add safety constraints to prompt

    Returns:
        RefinementResult with refined prompt and metadata
    """
    original = prompt.strip()
    refined = original
    applied_rules: List[str] = []
    warnings: List[str] = []

    # Check for unrefinable content first
    block_reason = _check_unrefinable(original)
    if block_reason:
        return RefinementResult(
            original=original,
            refined="",
            blocked=True,
            block_reason=block_reason,
        )

    # For SFW content, apply stricter refinement
    if content_rating == "sfw":
        # Remove any mature content references entirely
        refined = re.sub(r"\b(erotic|sensual|intimate|seductive)\b", "emotional", refined, flags=re.IGNORECASE)
        applied_rules.append("SFW: Replaced mature tone words")

    # For mature content, apply softening and enhancements
    if content_rating == "mature":
        # Affirm adult characters
        refined = _add_adult_affirmation(refined)
        applied_rules.append("Added adult character affirmation")

        # Apply softening rules
        if apply_softening:
            refined, softening_applied = _apply_softening(refined, MATURE_SOFTENING_RULES)
            applied_rules.extend(softening_applied)

        # Check for fade-to-black triggers
        refined, needs_fade = _add_fade_to_black(refined)
        if needs_fade:
            warnings.append("Scene may need 'fade to black' - intimate moments should be implied, not described")

        # Add constraints if requested
        if add_constraints:
            constraints = [
                "Focus on emotional connection and atmosphere.",
                "Use literary prose - evocative, not explicit.",
                "Imply intimacy rather than describing it.",
            ]
            refined = f"{refined}\n\n[Writing constraints: {' '.join(constraints)}]"
            applied_rules.append("Added literary constraints")

    return RefinementResult(
        original=original,
        refined=refined,
        applied_rules=applied_rules,
        warnings=warnings,
        blocked=False,
    )


def get_regeneration_options() -> List[Dict[str, str]]:
    """
    Get available regeneration constraint options for UI.

    These allow users to adjust output without re-prompting.
    """
    return [
        {
            "id": "more_romantic",
            "label": "More Romantic",
            "description": "Increase emotional warmth and connection",
            "constraint": "Emphasize emotional connection and romantic tension.",
        },
        {
            "id": "less_explicit",
            "label": "Less Explicit",
            "description": "Pull back on sensuality, more subtle",
            "constraint": "Be more subtle. Focus on implication and atmosphere.",
        },
        {
            "id": "fade_to_black",
            "label": "Fade to Black",
            "description": "End scene before intimate moments",
            "constraint": "End the scene before any intimate moments. Use 'fade to black' technique.",
        },
        {
            "id": "more_tension",
            "label": "More Tension",
            "description": "Build anticipation and slow burn",
            "constraint": "Build more anticipation. Slow the pace, increase tension.",
        },
        {
            "id": "literary_prose",
            "label": "More Literary",
            "description": "Elevate prose quality",
            "constraint": "Write with more literary quality. Evocative imagery, thoughtful prose.",
        },
    ]


def apply_regeneration_constraint(prompt: str, constraint_id: str) -> str:
    """Apply a regeneration constraint to a prompt."""
    options = {opt["id"]: opt["constraint"] for opt in get_regeneration_options()}

    constraint = options.get(constraint_id)
    if constraint:
        return f"{prompt}\n\n[Regeneration constraint: {constraint}]"

    return prompt


# ============================================================================
# OUTPUT VALIDATION
# ============================================================================

def validate_output(
    text: str,
    content_rating: ContentRating,
) -> Tuple[bool, List[str]]:
    """
    Validate generated output against content policies.

    Returns:
        (is_valid, list_of_issues)
    """
    issues = []

    # Check for explicit content that shouldn't appear
    explicit_patterns = [
        (r"\b(penis|vagina|genitals?)\b", "Explicit anatomical terms"),
        (r"\b(orgasm|climax)ed?\b", "Explicit sexual mechanics"),
        (r"\b(thrust|penetrat|pound)(ing|ed|s)?\b", "Explicit action descriptions"),
        (r"\b(moan|groan|scream)(ing|ed|s)?\s+(in|with)\s+(pleasure|ecstasy)\b", "Explicit reaction descriptions"),
    ]

    for pattern, description in explicit_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            issues.append(f"Contains {description}")

    # For SFW, check for any sensual content
    if content_rating == "sfw":
        sensual_patterns = [
            (r"\b(kiss(ed|ing)?|caress(ed|ing)?|embrac(e|ed|ing))\b.*\b(passionate|intimate|deeply)\b", "Sensual content in SFW mode"),
        ]
        for pattern, description in sensual_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                issues.append(description)

    is_valid = len(issues) == 0
    return is_valid, issues
