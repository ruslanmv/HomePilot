"""
Service layer for Studio operations.

Orchestrates business logic between repo, policy, and audit.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .models import StudioVideoCreate, StudioVideo, GenerationRequest
from .repo import create_video, get_video, touch, update_video
from .audit import log_event
from .policy import enforce_policy, get_policy_summary


def create(inp: StudioVideoCreate, actor: str = "system") -> StudioVideo:
    """
    Create a new Studio video project.

    Args:
        inp: Video creation parameters
        actor: User/system creating the video

    Returns:
        The created StudioVideo
    """
    v = create_video(inp)

    log_event(
        v.id,
        "create_video",
        {
            "title": v.title,
            "contentRating": v.contentRating,
            "policyMode": v.policyMode,
            "platformPreset": v.platformPreset,
        },
        actor=actor
    )

    return v


def policy_check_generation(
    *,
    video_id: str,
    prompt: str,
    provider: str,
    actor: str = "system",
) -> Dict[str, Any]:
    """
    Check if a generation prompt is allowed by policy.

    Args:
        video_id: The video project ID
        prompt: The generation prompt
        provider: The LLM/image provider
        actor: User/system making the request

    Returns:
        Dict with 'ok' boolean, and 'error'/'flags' on failure
    """
    v = get_video(video_id)
    if not v:
        return {"ok": False, "error": "Video not found"}

    decision = enforce_policy(
        prompt=prompt,
        content_rating=v.contentRating,
        policy_mode=v.policyMode,
        provider=provider,
        provider_policy=v.providerPolicy,
    )

    log_event(
        video_id,
        "policy_check",
        {
            "allowed": decision.allowed,
            "reason": decision.reason,
            "flags": decision.flags,
            "provider": provider,
            "prompt_preview": prompt[:100] + "..." if len(prompt) > 100 else prompt,
        },
        actor=actor,
    )

    if not decision.allowed:
        return {
            "ok": False,
            "error": decision.reason,
            "flags": decision.flags
        }

    touch(video_id)
    return {"ok": True, "flags": decision.flags}


def get_video_policy_summary(video_id: str) -> Optional[Dict[str, Any]]:
    """Get policy summary for a video project."""
    v = get_video(video_id)
    if not v:
        return None

    return get_policy_summary(v.contentRating, v.providerPolicy)


def update_content_rating(
    video_id: str,
    content_rating: str,
    actor: str = "system"
) -> Optional[StudioVideo]:
    """Update a video's content rating."""
    v = update_video(video_id, contentRating=content_rating)
    if v:
        log_event(
            video_id,
            "update_content_rating",
            {"contentRating": content_rating},
            actor=actor
        )
    return v
