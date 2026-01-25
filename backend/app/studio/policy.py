"""
NSFW Policy Engine for Studio.

Implements enterprise-grade content governance:
- SFW mode: Blocks explicit sexual content
- Mature mode: Allows literary erotica / adult romance themes
- Always blocks illegal/harmful content (CSAM, etc.)

MATURE MODE PHILOSOPHY:
"Mature" means literary erotica - emotional intimacy, desire, tension.
NOT explicit pornography. Think published romance novels, not explicit content.

Allowed in Mature:
- Sensuality, desire, romantic tension
- Emotional intimacy, attraction
- Implication and atmosphere
- Literary erotic prose

NOT allowed even in Mature:
- Explicit sexual mechanics/acts
- Graphic anatomical descriptions
- Minors in any romantic/sexual context
- Non-consensual scenarios
- Pornographic language
"""
from __future__ import annotations

import os
import re
from typing import List, Tuple

from .models import PolicyDecision, ContentRating, PolicyMode, ProviderPolicy

# ============================================================================
# POLICY TIERS
# ============================================================================

# TIER 1: ABSOLUTE BLOCK - Never allowed, any mode (illegal/harmful)
ABSOLUTE_BLOCKLIST = [
    r"\bchild\b.*\b(nude|sex|porn|erotic|intimate)\b",
    r"\bminor\b.*\b(nude|sex|porn|erotic|intimate)\b",
    r"\bunder\s*age\b.*\b(sex|nude|intimate)\b",
    r"\bloli\b",
    r"\bshota\b",
    r"\bincest\b",
    r"\brape\b",
    r"\b(non-?consensual|without consent)\b.*\b(sex|intimate)\b",
    r"\bcsam\b",
    r"\bpedophil",
    r"\bbestiality\b",
    r"\b(force|forced|forcing)\s+(sex|himself|herself|them)\b",
]

# TIER 2: SFW BLOCK - Blocked in SFW mode, may be allowed in Mature
SFW_BLOCKLIST = [
    r"\bexplicit\s+sex\b",
    r"\bporn\b",
    r"\berotic\b",
    r"\bsexual\s+content\b",
    r"\badult\s+content\b",
    r"\bnsfw\b",
    r"\bsensual\b",
    r"\bseductive\b",
    r"\bintimate\s+(scene|moment|encounter)\b",
]

# TIER 3: EXPLICIT BLOCK - Blocked even in Mature mode (too explicit)
# These are pornographic, not literary
EXPLICIT_BLOCKLIST = [
    # Crude language
    r"\bfuck(ing|ed)?\s+(her|him|me|them)\b",
    r"\bblowjob\b",
    r"\bcum(ming|med)?\b",
    r"\bdick\b",
    r"\bcock\b",
    r"\bpussy\b",
    r"\btits\b",

    # Explicit mechanics
    r"\bpenetrat(e|ed|ing|ion)\b",
    r"\bthrust(ing|ed)?\s+(into|inside)\b",
    r"\borgasm(ed|ing)?\b",
    r"\bejaculat",
    r"\bmasturbat",

    # Pornographic framing
    r"\bporn\s*star\b",
    r"\bxxx\b",
    r"\bhardcore\b",
    r"\bgangbang\b",
    r"\borgy\b",
]

# TIER 4: MATURE ALLOWED - Literary/romantic terms allowed in Mature mode
# These are NOT blocked in Mature mode
MATURE_ALLOWED_TERMS = [
    r"\bdesire\b",
    r"\blonging\b",
    r"\battraction\b",
    r"\btension\b",
    r"\bintimacy\b",
    r"\bpassion(ate)?\b",
    r"\bromantic\b",
    r"\bsensual\b",  # Allowed in mature, blocked in SFW
    r"\bseduct(ive|ion)\b",  # Allowed in mature, blocked in SFW
    r"\bkiss(ed|ing)?\b",
    r"\bcaress(ed|ing)?\b",
    r"\bembrace[ds]?\b",
    r"\btouch(ed|ing)?\b",
    r"\bundress(ed|ing)?\b",
    r"\bnaked\b",  # Literary term, allowed
    r"\bbare\s+skin\b",
]


def _compile_patterns(patterns: List[str]) -> List[re.Pattern]:
    """Compile regex patterns, skipping invalid ones."""
    compiled = []
    for p in patterns:
        try:
            compiled.append(re.compile(p, flags=re.IGNORECASE))
        except re.error:
            continue
    return compiled


# Compile all pattern lists
_ABSOLUTE_RE = _compile_patterns(ABSOLUTE_BLOCKLIST)
_SFW_RE = _compile_patterns(SFW_BLOCKLIST)
_EXPLICIT_RE = _compile_patterns(EXPLICIT_BLOCKLIST)
_MATURE_ALLOWED_RE = _compile_patterns(MATURE_ALLOWED_TERMS)


def _check_patterns(text: str, patterns: List[re.Pattern]) -> Tuple[bool, str]:
    """Check text against patterns, return (matched, pattern_preview)."""
    for rx in patterns:
        match = rx.search(text)
        if match:
            return True, match.group(0)[:50]
    return False, ""


def org_allows_mature() -> bool:
    """
    Check if organization-level policy allows mature content.

    For self-hosted deployments, mature content is allowed by default when
    content rating is set to "mature". Enterprise deployments can disable
    by setting STUDIO_ALLOW_MATURE=0.
    """
    return os.getenv("STUDIO_ALLOW_MATURE", "1").strip() != "0"


def enforce_policy(
    *,
    prompt: str,
    content_rating: ContentRating,
    policy_mode: PolicyMode,
    provider: str,
    provider_policy: ProviderPolicy,
) -> PolicyDecision:
    """
    Enforce content policy on a generation prompt.

    Policy Tiers:
    1. ABSOLUTE: Always blocked (illegal/harmful) - any mode
    2. EXPLICIT: Blocked even in Mature (pornographic, not literary)
    3. SFW: Blocked in SFW, allowed in Mature (sensual/romantic)
    4. MATURE ALLOWED: Literary terms allowed in Mature mode

    Args:
        prompt: The generation prompt to check
        content_rating: sfw or mature
        policy_mode: youtube_safe or restricted
        provider: The LLM/image provider being used
        provider_policy: Project-level provider restrictions

    Returns:
        PolicyDecision with allowed status and reason
    """
    text = (prompt or "").strip()

    if not text:
        return PolicyDecision(allowed=False, reason="Empty prompt")

    # ========================================================================
    # TIER 1: ABSOLUTE SAFETY - Always block (illegal/harmful)
    # ========================================================================
    matched, term = _check_patterns(text, _ABSOLUTE_RE)
    if matched:
        return PolicyDecision(
            allowed=False,
            reason=f"Blocked by absolute safety baseline (illegal/harmful content)",
            flags=["absolute_block", "safety_violation", f"matched:{term}"]
        )

    # ========================================================================
    # SFW MODE
    # ========================================================================
    if content_rating == "sfw":
        # Block any mature/sensual content
        matched, term = _check_patterns(text, _SFW_RE)
        if matched:
            return PolicyDecision(
                allowed=False,
                reason=f"Blocked by SFW policy - try enabling Mature mode for adult content",
                flags=["sfw_block", f"matched:{term}"]
            )

        # Also block explicit content in SFW
        matched, term = _check_patterns(text, _EXPLICIT_RE)
        if matched:
            return PolicyDecision(
                allowed=False,
                reason=f"Explicit content blocked in SFW mode",
                flags=["sfw_block", "explicit", f"matched:{term}"]
            )

        # YouTube-safe mode: additional monetization-safe checks
        if policy_mode == "youtube_safe":
            # Could add gore/violence limits here
            pass

        return PolicyDecision(allowed=True, reason="Allowed (SFW)")

    # ========================================================================
    # MATURE MODE - Literary erotica/adult romance allowed
    # ========================================================================

    # Gate 1: Organization must allow mature content
    if not org_allows_mature():
        return PolicyDecision(
            allowed=False,
            reason="Organization policy disables mature content. Set STUDIO_ALLOW_MATURE=1 to enable.",
            flags=["org_disallows_mature"]
        )

    # Gate 2: Project must explicitly enable mature generation
    if not provider_policy.allowMature:
        return PolicyDecision(
            allowed=False,
            reason="Project provider policy disallows mature generation. Enable in project settings.",
            flags=["project_disallows_mature"]
        )

    # Gate 3: Provider must be in allowlist
    allowed_providers = set(provider_policy.allowedProviders or [])
    if provider not in allowed_providers:
        return PolicyDecision(
            allowed=False,
            reason=f"Provider '{provider}' not approved for mature content. Allowed: {allowed_providers}",
            flags=["provider_not_allowed"]
        )

    # Gate 4: Local-only enforcement if configured
    if provider_policy.localOnly and provider != "ollama":
        return PolicyDecision(
            allowed=False,
            reason="Mature mode requires local-only provider (ollama) for privacy",
            flags=["local_only_violation"]
        )

    # ========================================================================
    # TIER 2: EXPLICIT BLOCK - Even in Mature mode, pornographic content blocked
    # ========================================================================
    matched, term = _check_patterns(text, _EXPLICIT_RE)
    if matched:
        return PolicyDecision(
            allowed=False,
            reason=f"Explicit/pornographic content blocked. Mature mode allows literary erotica, not explicit content. Rephrase using softer, literary language.",
            flags=["explicit_block", "mature_but_explicit", f"matched:{term}"]
        )

    # ========================================================================
    # MATURE CONTENT ALLOWED
    # ========================================================================
    # At this point:
    # - All gates passed
    # - No absolute/explicit blocks triggered
    # - Literary/romantic terms are allowed

    # Check if content uses mature-allowed terms (for logging)
    uses_mature_terms, _ = _check_patterns(text, _MATURE_ALLOWED_RE)
    flags = ["mature_allowed"]
    if uses_mature_terms:
        flags.append("literary_mature_content")

    return PolicyDecision(
        allowed=True,
        reason="Allowed (Mature - literary adult content)",
        flags=flags
    )


def get_policy_summary(content_rating: ContentRating, provider_policy: ProviderPolicy) -> dict:
    """Get human-readable policy summary for UI display."""

    if content_rating == "sfw":
        allowed = [
            "General audience content",
            "Romance (non-sexual)",
            "Drama, thriller, comedy",
        ]
        blocked = [
            "Sexual/sensual content",
            "Explicit language",
            "Adult themes",
        ]
    else:  # mature
        allowed = [
            "Literary erotica / adult romance",
            "Sensuality, desire, romantic tension",
            "Emotional intimacy, attraction",
            "Implication and atmosphere",
            "Mature themes (horror, etc.)",
        ]
        blocked = [
            "Explicit sexual mechanics/acts",
            "Pornographic language",
            "Graphic anatomical descriptions",
            "Minors in any romantic context",
            "Non-consensual scenarios",
        ]

    return {
        "contentRating": content_rating,
        "orgAllowsMature": org_allows_mature(),
        "projectAllowsMature": provider_policy.allowMature,
        "allowedProviders": provider_policy.allowedProviders,
        "localOnly": provider_policy.localOnly,
        "allowed": allowed,
        "blocked": blocked,
        "guidelines": [
            "All characters must be adults (18+)",
            "Focus on emotional connection, not explicit acts",
            "Use 'fade to black' for intimate moments",
            "Literary quality over shock value",
        ] if content_rating == "mature" else [
            "Suitable for general audiences",
            "No sexual or mature content",
        ],
    }


def enforce_image_policy(
    *,
    prompt: str,
    content_rating: ContentRating,
    provider: str,
    provider_policy: ProviderPolicy,
) -> PolicyDecision:
    """
    Enforce content policy for IMAGE generation.

    Image generation is MORE PERMISSIVE than text generation:
    - When NSFW/mature is enabled, explicit content (porn) IS allowed
    - Only ABSOLUTE blocks apply (CSAM, non-consent, illegal)

    This is appropriate because:
    - Anime models (AOM3, Counterfeit, etc.) are designed for NSFW
    - Users enabling mature mode expect full adult content capability
    - Standard local-only provider restrictions still apply

    Args:
        prompt: The image generation prompt to check
        content_rating: sfw or mature
        provider: The image provider being used
        provider_policy: Project-level provider restrictions

    Returns:
        PolicyDecision with allowed status and reason
    """
    text = (prompt or "").strip()

    if not text:
        return PolicyDecision(allowed=False, reason="Empty prompt")

    # ========================================================================
    # TIER 1: ABSOLUTE SAFETY - Always block (illegal/harmful)
    # Same for ALL content types - no exceptions
    # ========================================================================
    matched, term = _check_patterns(text, _ABSOLUTE_RE)
    if matched:
        return PolicyDecision(
            allowed=False,
            reason=f"Blocked by absolute safety baseline (illegal/harmful content)",
            flags=["absolute_block", "safety_violation", f"matched:{term}"]
        )

    # ========================================================================
    # SFW MODE - Block explicit content
    # ========================================================================
    if content_rating == "sfw":
        # Block any mature/sensual content in SFW
        matched, term = _check_patterns(text, _SFW_RE)
        if matched:
            return PolicyDecision(
                allowed=False,
                reason=f"Blocked by SFW policy - enable Mature mode for adult content",
                flags=["sfw_block", f"matched:{term}"]
            )

        matched, term = _check_patterns(text, _EXPLICIT_RE)
        if matched:
            return PolicyDecision(
                allowed=False,
                reason=f"Explicit content blocked in SFW mode",
                flags=["sfw_block", "explicit", f"matched:{term}"]
            )

        return PolicyDecision(allowed=True, reason="Allowed (SFW image)")

    # ========================================================================
    # MATURE/NSFW MODE - Explicit content ALLOWED for images
    # ========================================================================

    # Gate 1: Organization must allow mature content
    if not org_allows_mature():
        return PolicyDecision(
            allowed=False,
            reason="Organization policy disables mature content. Set STUDIO_ALLOW_MATURE=1 to enable.",
            flags=["org_disallows_mature"]
        )

    # Gate 2: Project must explicitly enable mature generation
    if not provider_policy.allowMature:
        return PolicyDecision(
            allowed=False,
            reason="Project provider policy disallows mature generation. Enable in project settings.",
            flags=["project_disallows_mature"]
        )

    # Gate 3: Provider must be in allowlist
    allowed_providers = set(provider_policy.allowedProviders or [])
    if provider not in allowed_providers:
        return PolicyDecision(
            allowed=False,
            reason=f"Provider '{provider}' not approved for mature content. Allowed: {allowed_providers}",
            flags=["provider_not_allowed"]
        )

    # Gate 4: Local-only enforcement if configured
    if provider_policy.localOnly and provider not in ("comfyui", "ollama", "local"):
        return PolicyDecision(
            allowed=False,
            reason="Mature mode requires local-only provider for privacy",
            flags=["local_only_violation"]
        )

    # ========================================================================
    # IMAGE NSFW: EXPLICIT CONTENT ALLOWED
    # Only absolute blocks apply - porn/explicit is permitted
    # ========================================================================
    return PolicyDecision(
        allowed=True,
        reason="Allowed (NSFW image - explicit content permitted)",
        flags=["nsfw_image_allowed", "explicit_permitted"]
    )


def get_mature_content_guide() -> dict:
    """Get detailed guide for creating mature content appropriately."""
    return {
        "title": "Mature Romance / Adult Fiction Guide",
        "description": "How to create literary adult content that's allowed",
        "philosophy": (
            "Mature mode allows literary erotica - emotional intimacy, desire, tension. "
            "NOT explicit pornography. Think published romance novels, not explicit content."
        ),
        "allowed_elements": [
            "Emotional intimacy and connection",
            "Sensual atmosphere and mood",
            "Attraction and desire",
            "Romantic tension and anticipation",
            "Implication ('they drew closer', 'heat lingered')",
            "Tasteful physical awareness",
            "Literary prose quality",
        ],
        "blocked_elements": [
            "Explicit sexual acts",
            "Graphic anatomical descriptions",
            "Pornographic language",
            "Sexual mechanics",
            "Minors (even implied)",
            "Non-consensual scenarios",
            "Fetish content",
        ],
        "example_prompt": {
            "good": (
                "Genre: Mature romance\n"
                "Tone: Sensual, slow-burn\n"
                "Characters: Two consenting adults\n"
                "Setting: Candlelit room, evening\n"
                "Focus: The tension and anticipation between them"
            ),
            "bad": "Write explicit sex scene with graphic details",
        },
        "example_output": (
            "The candlelight softened the room, tracing warm shadows along the walls "
            "as they stood facing each other, close enough to feel the quiet pull between them.\n\n"
            "She smiled, slow and deliberate, aware of the way his attention lingered. "
            "There was no rush — just the shared understanding that the moment was theirs, "
            "unfolding at its own pace.\n\n"
            "When he reached for her hand, it felt less like a decision and more like inevitability — "
            "a promise of closeness, anticipation humming between them like a held breath."
        ),
        "tips": [
            "State 'all characters are adults (18+)' explicitly",
            "Focus on emotional connection first",
            "Use atmosphere and mood to convey sensuality",
            "Let readers fill in the blanks",
            "End scenes with 'fade to black' when appropriate",
        ],
    }
