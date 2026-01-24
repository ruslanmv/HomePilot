"""
Studio data models with NSFW governance support.

Content ratings:
  - sfw: Safe for work (default). Blocks explicit content.
  - mature: Allows mature themes (horror, anatomy, fashion, etc.)
            Only when org + project policies allow.

Policy modes:
  - youtube_safe: Strictest. YouTube monetization compatible.
  - restricted: Allows mature with proper gating.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

# Type aliases for content governance
ContentRating = Literal["sfw", "mature"]
PolicyMode = Literal["youtube_safe", "restricted"]
PlatformPreset = Literal["youtube_16_9", "shorts_9_16", "slides_16_9"]
VideoStatus = Literal["draft", "in_review", "approved", "archived"]


class ProviderPolicy(BaseModel):
    """
    Provider-level policy for content generation.

    Attributes:
        allowMature: Whether this project allows mature generation
        allowedProviders: List of providers approved for mature content
        localOnly: If True, mature generation only on local providers (e.g., ollama)
    """
    allowMature: bool = False
    allowedProviders: List[str] = Field(default_factory=lambda: ["ollama"])
    localOnly: bool = True  # Default: no external API calls in mature mode


class StudioVideoCreate(BaseModel):
    """Request payload to create a new Studio video project."""
    title: str
    logline: Optional[str] = ""
    tags: List[str] = Field(default_factory=list)

    platformPreset: PlatformPreset = "youtube_16_9"
    targetDurationSec: Optional[int] = 180

    # NSFW governance
    contentRating: ContentRating = "sfw"
    policyMode: PolicyMode = "youtube_safe"
    providerPolicy: ProviderPolicy = Field(default_factory=ProviderPolicy)


class StudioVideo(BaseModel):
    """A Studio video project with all metadata."""
    id: str
    title: str
    logline: str = ""
    tags: List[str] = Field(default_factory=list)

    status: VideoStatus = "draft"
    platformPreset: PlatformPreset = "youtube_16_9"
    targetDurationSec: int = 180

    # NSFW governance
    contentRating: ContentRating = "sfw"
    policyMode: PolicyMode = "youtube_safe"
    providerPolicy: ProviderPolicy = Field(default_factory=ProviderPolicy)

    createdAt: float
    updatedAt: float


class PolicyDecision(BaseModel):
    """Result of a policy check for content generation."""
    allowed: bool
    reason: str = ""
    flags: List[str] = Field(default_factory=list)


class AuditEvent(BaseModel):
    """Audit log entry for compliance tracking."""
    eventId: str
    videoId: str
    actor: str = "system"
    type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float


class GenerationRequest(BaseModel):
    """Request to generate content with policy enforcement."""
    prompt: str
    provider: str = "ollama"


class ExportRequest(BaseModel):
    """Request to export video assets."""
    kind: Literal["zip_assets", "storyboard_pdf", "json_metadata", "slides_pack"] = "zip_assets"


# ============================================================================
# Scene Models
# ============================================================================

SceneStatus = Literal["pending", "generating", "ready", "error"]


class StudioScene(BaseModel):
    """A scene within a Studio video project."""
    id: str
    videoId: str
    idx: int  # Scene order index

    # Content
    narration: str = ""
    imagePrompt: str = ""
    negativePrompt: str = ""

    # Generated assets
    imageUrl: Optional[str] = None
    audioUrl: Optional[str] = None

    # Generation status
    status: SceneStatus = "pending"

    # Timing
    durationSec: float = 5.0
    createdAt: float = 0.0
    updatedAt: float = 0.0


class StudioSceneCreate(BaseModel):
    """Request payload to create a new scene."""
    narration: str = ""
    imagePrompt: str = ""
    negativePrompt: str = ""
    durationSec: float = 5.0


class StudioSceneUpdate(BaseModel):
    """Request payload to update a scene."""
    narration: Optional[str] = None
    imagePrompt: Optional[str] = None
    negativePrompt: Optional[str] = None
    imageUrl: Optional[str] = None
    audioUrl: Optional[str] = None
    status: Optional[SceneStatus] = None
    durationSec: Optional[float] = None
