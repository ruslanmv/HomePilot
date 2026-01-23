"""
Export functionality for Studio video projects.

Supported export formats:
- zip_assets: ZIP file with all generated assets
- storyboard_pdf: PDF storyboard document
- json_metadata: JSON file with project metadata
- slides_pack: Presentation-ready slide pack

POLICY: No exports targeted to adult platforms.
Mature content exports may have additional restrictions.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from .repo import get_video
from .audit import log_event


# Export targets that are NOT allowed (safety baseline)
BLOCKED_EXPORT_TARGETS = [
    # No adult platform integrations - this is YouTube/presentation focused
]


def export_pack(
    video_id: str,
    kind: str = "zip_assets",
    actor: str = "system"
) -> Dict[str, Any]:
    """
    Export video project assets.

    Args:
        video_id: The video project ID
        kind: Export type (zip_assets, storyboard_pdf, json_metadata, slides_pack)
        actor: User/system requesting export

    Returns:
        Export result with status and download info
    """
    v = get_video(video_id)
    if not v:
        return {"ok": False, "error": "Video not found"}

    # Check for mature content export restrictions
    restrictions = []
    if v.contentRating == "mature":
        restrictions.append("Mature content - verify compliance before sharing")
        # Could add additional restrictions here

    log_event(
        video_id,
        "export",
        {
            "kind": kind,
            "contentRating": v.contentRating,
            "restrictions": restrictions,
        },
        actor=actor
    )

    # MVP: Return placeholder. Wire real exporters in production.
    return {
        "ok": True,
        "videoId": video_id,
        "kind": kind,
        "status": "not_implemented",
        "restrictions": restrictions,
        "message": "Export functionality coming soon. Assets will be at /studio/exports/{video_id}/{kind}",
    }


def get_available_exports(video_id: str) -> Dict[str, Any]:
    """Get list of available export formats for a video."""
    v = get_video(video_id)
    if not v:
        return {"ok": False, "error": "Video not found"}

    exports = [
        {"kind": "zip_assets", "label": "Asset Pack (ZIP)", "available": True},
        {"kind": "storyboard_pdf", "label": "Storyboard (PDF)", "available": True},
        {"kind": "json_metadata", "label": "Metadata (JSON)", "available": True},
        {"kind": "slides_pack", "label": "Slides Pack", "available": v.platformPreset == "slides_16_9"},
    ]

    return {
        "ok": True,
        "exports": exports,
        "contentRating": v.contentRating,
    }
