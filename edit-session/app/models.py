"""
Pydantic models for request/response validation.

These models define the API contract for the edit-session service.
"""

from pydantic import BaseModel, Field
from typing import Any, Optional, List, Dict


class VersionEntryModel(BaseModel):
    """
    Represents a single version in the edit history.
    """
    url: str = Field(..., description="Image URL for this version")
    instruction: str = Field(default="", description="Edit instruction used to create this version")
    created_at: float = Field(..., description="Unix timestamp when this version was created")
    parent_url: Optional[str] = Field(default=None, description="URL of the parent image")
    settings: Dict[str, Any] = Field(default_factory=dict, description="Edit settings used")


class UploadResponse(BaseModel):
    """Response returned after successful image upload."""
    url: str = Field(..., description="URL of the uploaded image")


class ProxyChatRequest(BaseModel):
    """
    Request model for the /chat proxy endpoint.

    Compatible with HomePilot's /chat endpoint format.
    """
    message: str = Field(..., description="User's message or edit instruction")
    mode: Optional[str] = Field(
        None,
        description="Operating mode: chat|imagine|edit|animate|project"
    )
    conversation_id: Optional[str] = Field(
        None,
        description="Conversation ID for session tracking"
    )

    # Passthrough settings commonly present in HomePilot
    provider: Optional[str] = Field(None, description="LLM provider name")
    provider_base_url: Optional[str] = Field(None, description="Custom provider URL")
    model: Optional[str] = Field(None, description="Model identifier")
    stream: Optional[bool] = Field(None, description="Enable streaming response")

    # Allow any additional fields without breaking (forward compatibility)
    extra: Dict[str, Any] = Field(default_factory=dict)

    def to_forward_payload(self) -> Dict[str, Any]:
        """Convert to payload dictionary for forwarding to HomePilot."""
        payload = {
            "message": self.message,
            "mode": self.mode,
            "conversation_id": self.conversation_id,
            "provider": self.provider,
            "provider_base_url": self.provider_base_url,
            "model": self.model,
            "stream": self.stream,
        }
        # Include extra keys
        payload.update(self.extra)
        # Remove None values
        return {k: v for k, v in payload.items() if v is not None}


class EditSessionState(BaseModel):
    """Current state of an edit session."""
    conversation_id: str = Field(..., description="Unique session identifier")
    active_image_url: Optional[str] = Field(
        None,
        description="Currently active image URL for editing"
    )
    original_image_url: Optional[str] = Field(
        None,
        description="The first image uploaded to this session"
    )
    versions: List[VersionEntryModel] = Field(
        default_factory=list,
        description="List of version entries with metadata (most recent first)"
    )
    history: List[str] = Field(
        default_factory=list,
        description="Legacy: List of previous image URLs (use versions for full metadata)"
    )


class SetActiveImageResponse(BaseModel):
    """Response after setting an active image."""
    conversation_id: str
    active_image_url: str
    history: List[str]


class EditMessageRequest(BaseModel):
    """Request model for natural language edit operations."""
    message: str = Field(..., description="Natural language edit instruction")
    provider: Optional[str] = Field(None, description="LLM provider name")
    provider_base_url: Optional[str] = Field(None, description="Custom provider URL")
    model: Optional[str] = Field(None, description="Model identifier")
    stream: Optional[bool] = Field(None, description="Enable streaming response")
    extra: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional parameters to forward"
    )


class SelectImageRequest(BaseModel):
    """Request to select an image as the new active base."""
    image_url: str = Field(..., description="URL of the image to set as active")


class HomePilotChatResponse(BaseModel):
    """
    Wrapper for HomePilot chat responses.

    Kept flexible to accommodate various response shapes.
    """
    raw: Dict[str, Any] = Field(..., description="Raw response from HomePilot")


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Service status: ok or error")
    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Service version")
    store: str = Field(..., description="Storage backend type")
    home_pilot_base_url: str = Field(..., description="HomePilot backend URL")


class ErrorResponse(BaseModel):
    """Standard error response."""
    detail: str = Field(..., description="Error message")
    error_code: Optional[str] = Field(None, description="Machine-readable error code")
