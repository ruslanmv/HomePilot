"""
Story Genre Definitions for Studio.

Defines supported story genres including mature romance/adult fiction
with appropriate content guidelines and prompt templates.

IMPORTANT: "Mature Romance" means literary erotica - focus on:
- Emotional intimacy, tension, desire
- All characters explicitly adults (18+)
- Sensuality and mood, NOT explicit acts
- Literary quality over shock value
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from enum import Enum


class StoryTone(str, Enum):
    """Available story tones."""
    ROMANTIC = "romantic"
    SENSUAL = "sensual"
    SLOW_BURN = "slow_burn"
    PASSIONATE = "passionate"
    TENDER = "tender"
    PLAYFUL = "playful"
    MYSTERIOUS = "mysterious"
    DRAMATIC = "dramatic"


class ExplicitnessLevel(str, Enum):
    """
    Content explicitness levels for mature content.

    FADE_TO_BLACK: Implication only, scene ends before intimacy
    SUGGESTIVE: Tension and desire, no physical description
    SENSUAL: Emotional/atmospheric intimacy, tasteful
    """
    FADE_TO_BLACK = "fade_to_black"
    SUGGESTIVE = "suggestive"
    SENSUAL = "sensual"
    # Note: "explicit" is NOT supported - this is literary, not pornographic


class StoryGenre(BaseModel):
    """Definition of a story genre with content guidelines."""
    id: str
    name: str
    description: str
    requires_mature: bool = False
    default_tone: StoryTone = StoryTone.ROMANTIC
    allowed_tones: List[StoryTone] = Field(default_factory=list)
    content_guidelines: List[str] = Field(default_factory=list)
    blocked_elements: List[str] = Field(default_factory=list)
    example_themes: List[str] = Field(default_factory=list)


class MatureStoryConfig(BaseModel):
    """Configuration for mature story generation."""
    genre: str = "mature_romance"
    tone: StoryTone = StoryTone.SENSUAL
    explicitness: ExplicitnessLevel = ExplicitnessLevel.SUGGESTIVE

    # Character requirements
    all_characters_adult: bool = True  # Must be True, enforced
    character_age_minimum: int = 18    # Enforced

    # Content boundaries
    focus_on_emotion: bool = True
    allow_physical_description: bool = False  # Atmospheric only
    fade_to_black: bool = True  # Default safe

    # Output constraints
    max_sensuality_score: int = 3  # 1-5 scale, 3 = tasteful


# ============================================================================
# GENRE DEFINITIONS
# ============================================================================

GENRES: Dict[str, StoryGenre] = {
    # Standard genres (SFW)
    "drama": StoryGenre(
        id="drama",
        name="Drama",
        description="Character-driven emotional narratives",
        requires_mature=False,
        default_tone=StoryTone.DRAMATIC,
        allowed_tones=[StoryTone.DRAMATIC, StoryTone.TENDER, StoryTone.MYSTERIOUS],
        content_guidelines=[
            "Focus on character development and emotional arcs",
            "Conflict drives the narrative",
            "Suitable for general audiences",
        ],
        example_themes=["family conflict", "career struggles", "personal growth"],
    ),

    "romance": StoryGenre(
        id="romance",
        name="Romance",
        description="Love stories with emotional connection (SFW)",
        requires_mature=False,
        default_tone=StoryTone.ROMANTIC,
        allowed_tones=[StoryTone.ROMANTIC, StoryTone.TENDER, StoryTone.PLAYFUL],
        content_guidelines=[
            "Focus on emotional connection between characters",
            "Building relationship over time",
            "Suitable for general audiences",
            "No sexual content",
        ],
        example_themes=["first love", "second chances", "workplace romance"],
    ),

    "thriller": StoryGenre(
        id="thriller",
        name="Thriller",
        description="Suspenseful, tension-driven narratives",
        requires_mature=False,
        default_tone=StoryTone.MYSTERIOUS,
        allowed_tones=[StoryTone.MYSTERIOUS, StoryTone.DRAMATIC],
        content_guidelines=[
            "Build suspense and tension",
            "Stakes should feel real",
            "Suitable for general audiences",
        ],
        example_themes=["mystery", "chase", "conspiracy"],
    ),

    # Mature genres (require content rating = mature)
    "mature_romance": StoryGenre(
        id="mature_romance",
        name="Mature Romance / Adult Fiction",
        description="Literary erotica with emotional depth - sensual but not explicit",
        requires_mature=True,
        default_tone=StoryTone.SENSUAL,
        allowed_tones=[StoryTone.SENSUAL, StoryTone.SLOW_BURN, StoryTone.PASSIONATE, StoryTone.TENDER],
        content_guidelines=[
            "ALL characters must be explicitly adults (18+)",
            "Focus on desire, intimacy, tension, and mood",
            "Emotional connection is primary",
            "Sensuality through atmosphere, not explicit description",
            "Literary quality over shock value",
            "Consent must be clear between characters",
            "No graphic sexual acts or anatomical detail",
        ],
        blocked_elements=[
            "Explicit sexual mechanics",
            "Graphic anatomical descriptions",
            "Minors in any romantic/sexual context",
            "Non-consensual scenarios",
            "Fetish content",
            "Pornographic language",
        ],
        example_themes=[
            "forbidden attraction",
            "slow-burn romance",
            "reunion of past lovers",
            "emotional intimacy",
            "romantic tension",
        ],
    ),

    "dark_fiction": StoryGenre(
        id="dark_fiction",
        name="Dark Fiction",
        description="Mature themes including horror, psychological darkness",
        requires_mature=True,
        default_tone=StoryTone.MYSTERIOUS,
        allowed_tones=[StoryTone.MYSTERIOUS, StoryTone.DRAMATIC],
        content_guidelines=[
            "Psychological depth over shock",
            "Horror/dark themes handled with craft",
            "No gratuitous violence for its own sake",
            "Appropriate for mature readers",
        ],
        blocked_elements=[
            "Torture porn",
            "Graphic violence against children",
            "Real-world harm instructions",
        ],
        example_themes=["psychological horror", "gothic", "dark fantasy"],
    ),
}


def get_genre(genre_id: str) -> Optional[StoryGenre]:
    """Get a genre by ID."""
    return GENRES.get(genre_id)


def get_mature_genres() -> List[StoryGenre]:
    """Get all genres that require mature content rating."""
    return [g for g in GENRES.values() if g.requires_mature]


def get_sfw_genres() -> List[StoryGenre]:
    """Get all SFW genres."""
    return [g for g in GENRES.values() if not g.requires_mature]


def validate_genre_for_rating(genre_id: str, content_rating: str) -> tuple[bool, str]:
    """
    Check if a genre is allowed for the given content rating.

    Returns:
        (allowed, reason)
    """
    genre = get_genre(genre_id)
    if not genre:
        return False, f"Unknown genre: {genre_id}"

    if genre.requires_mature and content_rating != "mature":
        return False, f"Genre '{genre.name}' requires mature content rating"

    return True, "Allowed"


# ============================================================================
# PROMPT TEMPLATES FOR MATURE ROMANCE
# ============================================================================

MATURE_ROMANCE_SYSTEM_PROMPT = """You are a literary fiction writer specializing in mature romance and emotional storytelling.

CRITICAL RULES:
1. ALL characters are adults (18+) - state ages explicitly if relevant
2. Focus on EMOTIONAL intimacy, tension, desire, and mood
3. NO explicit sexual acts or graphic anatomy
4. NO pornographic language or mechanics
5. Consent between characters must be clear
6. Write with literary quality - evocative, not explicit
7. Use "fade to black" for intimate moments
8. Atmosphere and emotion over physical description

WRITING STYLE:
- Sensual but tasteful
- Show attraction through glances, touches, tension
- Build anticipation and desire
- Emotional connection is primary
- Implication over description
- Literary prose quality

EXAMPLE OF APPROPRIATE TONE:
"The candlelight softened the room, tracing warm shadows along the walls as they stood
facing each other, close enough to feel the quiet pull between them. She smiled, slow
and deliberate, aware of the way his attention lingered. There was no rush — just the
shared understanding that the moment was theirs."

DO NOT:
- Describe sexual acts explicitly
- Use crude or pornographic language
- Include minors in any romantic context
- Write non-consensual scenarios
- Include graphic anatomical details"""


MATURE_ROMANCE_USER_TEMPLATE = """Genre: Mature Romance / Adult Fiction
Audience: Adults only (18+)
Tone: {tone}
Explicitness: {explicitness} (literary, not explicit)

Setting: {setting}
Characters: {characters}

Story request: {prompt}

Remember: All characters are consenting adults. Focus on emotional intimacy and atmosphere.
No explicit content - use implication and "fade to black" for intimate moments."""


def build_mature_story_prompt(
    prompt: str,
    tone: StoryTone = StoryTone.SENSUAL,
    explicitness: ExplicitnessLevel = ExplicitnessLevel.SUGGESTIVE,
    setting: str = "unspecified",
    characters: str = "two consenting adults",
) -> dict:
    """
    Build a properly constrained prompt for mature story generation.

    Returns:
        Dict with 'system' and 'user' prompt components
    """
    tone_descriptions = {
        StoryTone.SENSUAL: "Sensual, emotionally intimate, atmospheric",
        StoryTone.SLOW_BURN: "Slow-burn, building tension gradually",
        StoryTone.PASSIONATE: "Passionate but tasteful, intense emotions",
        StoryTone.TENDER: "Tender, gentle, emotionally vulnerable",
        StoryTone.ROMANTIC: "Romantic, warm, connection-focused",
    }

    explicitness_descriptions = {
        ExplicitnessLevel.FADE_TO_BLACK: "Fade to black - scene ends before intimacy, implication only",
        ExplicitnessLevel.SUGGESTIVE: "Suggestive - tension and desire, no physical description",
        ExplicitnessLevel.SENSUAL: "Sensual - emotional/atmospheric intimacy, tasteful prose",
    }

    user_prompt = MATURE_ROMANCE_USER_TEMPLATE.format(
        tone=tone_descriptions.get(tone, "Sensual"),
        explicitness=explicitness_descriptions.get(explicitness, "Suggestive"),
        setting=setting or "unspecified",
        characters=characters or "two consenting adults",
        prompt=prompt,
    )

    return {
        "system": MATURE_ROMANCE_SYSTEM_PROMPT,
        "user": user_prompt,
        "metadata": {
            "genre": "mature_romance",
            "tone": tone.value,
            "explicitness": explicitness.value,
            "content_rating": "mature",
        }
    }
