"""
Personality Agent Type Definitions

Industry-grade Pydantic models for the personality agent framework.
Every personality is a PersonalityAgent — a structured, validated,
introspectable definition that drives real-time prompt assembly.

Design principles:
  - Pydantic v2 for validation + serialization
  - Immutable after creation (frozen=False for memory updates but agents are const)
  - JSON-serializable for the /api/personalities endpoint
  - No inheritance chains — flat, explicit, auditable
"""
from __future__ import annotations

from typing import List, Optional, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Voice presentation
# ---------------------------------------------------------------------------
class VoiceStyle(BaseModel):
    """TTS hints sent alongside the response so the frontend/TTS engine
    can adjust rate, pitch, and pause behavior per personality."""
    rate_bias: float = Field(1.0, ge=0.5, le=2.0, description="Speech rate multiplier (0.75=slow, 1.2=fast)")
    pitch_bias: float = Field(1.0, ge=0.5, le=2.0, description="Pitch shift (0.9=deeper, 1.1=higher)")
    pause_style: Literal["natural", "dramatic", "rapid", "calm"] = "natural"


# ---------------------------------------------------------------------------
# Response formatting
# ---------------------------------------------------------------------------
class ResponseStyle(BaseModel):
    """Controls how the agent shapes its output."""
    max_length: Literal["short", "medium", "long"] = Field("short", description="Target response length for voice")
    tone: str = Field("friendly", description="Tonal quality descriptor")
    use_emoji: bool = Field(False, description="Whether to use emoji in responses")


# ---------------------------------------------------------------------------
# Safety & gating
# ---------------------------------------------------------------------------
class Safety(BaseModel):
    """Content safety constraints. Checked before the agent is activated."""
    requires_adult_gate: bool = False
    allow_explicit: bool = False
    content_warning: Optional[str] = None


# ---------------------------------------------------------------------------
# Conversation dynamics
# ---------------------------------------------------------------------------
class ConversationDynamics(BaseModel):
    """Behavioral profile that shapes how the agent drives conversation."""
    initiative: Literal["passive", "balanced", "proactive", "leading"] = Field(
        "balanced",
        description="How much the agent takes the lead vs follows",
    )
    speak_listen_ratio: float = Field(
        1.0, ge=0.1, le=5.0,
        description="Ratio >1 means agent speaks more, <1 means listens more",
    )
    depth: Literal["surface", "moderate", "deep", "exhaustive"] = Field(
        "moderate",
        description="How deep to explore a single topic before moving on",
    )
    emotional_base: str = Field("warm", description="Default emotional tone")
    mirror_emotion: bool = Field(False, description="Whether to match user's emotional state")
    intensity_pattern: Literal["steady", "building", "waves", "responsive"] = Field(
        "steady",
        description="How emotional intensity evolves across the conversation",
    )


# ---------------------------------------------------------------------------
# Engagement hooks
# ---------------------------------------------------------------------------
class EngagementHook(BaseModel):
    """A conversational hook the agent can deploy to keep engagement alive."""
    trigger: Literal[
        "silence",           # User goes quiet
        "topic_exhausted",   # Current topic runs dry
        "emotional_peak",    # User shows strong emotion
        "random",            # Probabilistic injection
        "on_answer",         # After any user response
    ]
    template: str = Field(..., description="Hook text (may contain {topic}, {emotion} placeholders)")
    probability: float = Field(0.3, ge=0.0, le=1.0, description="Chance of deploying this hook")


# ---------------------------------------------------------------------------
# Opening behavior
# ---------------------------------------------------------------------------
class OpeningBehavior(BaseModel):
    """How the agent starts a new conversation."""
    style: Literal["greeting", "question", "statement", "observation", "game_start"] = "greeting"
    templates: List[str] = Field(default_factory=list, description="Opening line templates")
    acknowledge_return: bool = Field(True, description="Whether to acknowledge returning users")


# ---------------------------------------------------------------------------
# Silence handling
# ---------------------------------------------------------------------------
class SilenceStrategy(BaseModel):
    """How the agent responds to user silence or minimal input."""
    wait_seconds: float = Field(5.0, ge=1.0, le=30.0, description="Seconds before re-engaging")
    on_minimal_response: Literal["probe_deeper", "change_topic", "offer_options", "share_thought"] = "probe_deeper"
    re_engage_templates: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Follow-up behavior
# ---------------------------------------------------------------------------
class FollowUpStrategy(BaseModel):
    """How the agent circles back to previous topics."""
    delay_turns: int = Field(3, ge=1, description="Turns before following up on a past topic")
    templates: List[str] = Field(default_factory=list)
    use_specific_callbacks: bool = Field(True, description="Reference specific details the user mentioned")


# ---------------------------------------------------------------------------
# The complete personality agent
# ---------------------------------------------------------------------------
class PersonalityAgent(BaseModel):
    """
    Complete personality definition — the single source of truth.

    This replaces:
      - frontend personalities.ts (basic prompt + label)
      - frontend personalityCaps.ts (psychology, voice style, safety)
      - frontend conversationStrategy.ts (dynamics, hooks, engagement)

    All three are now unified in ONE backend-authoritative model.
    """
    # Identity
    id: str = Field(..., description="Unique personality identifier (e.g. 'therapist')")
    label: str = Field(..., description="Human-readable display name")
    category: Literal["general", "kids", "wellness", "adult"] = "general"

    # Core behavioral prompt — the rich, production-grade system prompt
    system_prompt: str = Field(..., description="The detailed system prompt that defines this agent's behavior")

    # Psychological grounding
    psychology_approach: str = Field("", description="Therapeutic/behavioral framework (e.g. 'Rogerian therapy + CBT')")
    key_techniques: List[str] = Field(default_factory=list, description="Specific techniques this personality uses")
    unique_behaviors: List[str] = Field(default_factory=list, description="Distinctive behavioral traits")

    # Conversation dynamics
    dynamics: ConversationDynamics = Field(default_factory=ConversationDynamics)
    opening: OpeningBehavior = Field(default_factory=OpeningBehavior)
    silence: SilenceStrategy = Field(default_factory=SilenceStrategy)
    follow_up: FollowUpStrategy = Field(default_factory=FollowUpStrategy)

    # Engagement tools
    engagement_hooks: List[EngagementHook] = Field(default_factory=list)
    empathy_phrases: List[str] = Field(default_factory=list)
    affirmations: List[str] = Field(default_factory=list)
    active_listening_cues: List[str] = Field(default_factory=list)
    investment_phrases: List[str] = Field(default_factory=list)

    # Presentation
    voice_style: VoiceStyle = Field(default_factory=VoiceStyle)
    response_style: ResponseStyle = Field(default_factory=ResponseStyle)
    safety: Safety = Field(default_factory=Safety)

    # Tool permissions — which actions this personality can trigger/suggest
    allowed_tools: List[str] = Field(
        default_factory=list,
        description="Tools this personality can proactively suggest (e.g. 'imagine', 'search', 'animate')",
    )

    # Visual identity — drives image generation when this personality is active
    image_style_hint: Optional[str] = Field(
        None,
        description=(
            "Short visual-style directive injected into the prompt refiner when "
            "this personality triggers image generation. Describes the aesthetic, "
            "mood, and visual language that images should follow."
        ),
    )
