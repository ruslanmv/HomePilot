"""
Export functionality for Studio video projects and professional projects.

Supported export formats:
- zip_assets: ZIP file with all generated assets
- storyboard_pdf: PDF storyboard document
- json_metadata: JSON file with project metadata
- slides_pack: Presentation-ready slide pack
- slides_pdf: PDF export of slides
- slides_pptx: PowerPoint export of slides

POLICY: No exports targeted to adult platforms.
Mature content exports may have additional restrictions.
"""
from __future__ import annotations

import io
import json
import time
import zipfile
from typing import Any, Dict, List, Optional

from .repo import get_video, get_project, list_assets, list_scenes
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


# ============================================================================
# Professional Project Exports
# ============================================================================

def export_project_json(project_id: str, actor: str = "system") -> Dict[str, Any]:
    """
    Export professional project as JSON metadata.

    Returns project configuration, scenes, and asset references.
    """
    proj = get_project(project_id)
    if not proj:
        return {"ok": False, "error": "Project not found"}

    assets = list_assets(project_id)

    log_event(
        project_id,
        "export_json",
        {"projectType": proj.projectType},
        actor=actor
    )

    export_data = {
        "version": "1.0",
        "exportedAt": time.time(),
        "project": proj.model_dump(),
        "assets": [a.model_dump() for a in assets],
    }

    return {
        "ok": True,
        "projectId": project_id,
        "kind": "json_metadata",
        "data": export_data,
        "filename": f"{proj.title.replace(' ', '_')}_metadata.json",
    }


def export_project_storyboard_pdf(project_id: str, actor: str = "system") -> Dict[str, Any]:
    """
    Export professional project as a storyboard PDF.

    Creates a visual storyboard with scene thumbnails and descriptions.
    Note: Actual PDF generation requires reportlab or similar library.
    """
    proj = get_project(project_id)
    if not proj:
        return {"ok": False, "error": "Project not found"}

    assets = list_assets(project_id, kind="image")

    log_event(
        project_id,
        "export_storyboard_pdf",
        {"projectType": proj.projectType, "assetCount": len(assets)},
        actor=actor
    )

    # MVP: Return storyboard data structure
    # Production: Use reportlab to generate actual PDF
    storyboard_data = {
        "title": proj.title,
        "description": proj.description,
        "projectType": proj.projectType,
        "canvas": proj.canvas.model_dump(),
        "frames": [],
    }

    for i, asset in enumerate(assets):
        storyboard_data["frames"].append({
            "index": i + 1,
            "imageUrl": asset.url,
            "filename": asset.filename,
        })

    return {
        "ok": True,
        "projectId": project_id,
        "kind": "storyboard_pdf",
        "status": "data_ready",
        "data": storyboard_data,
        "filename": f"{proj.title.replace(' ', '_')}_storyboard.pdf",
        "message": "PDF generation ready. Use /studio/projects/{id}/export/pdf to download.",
    }


def export_project_slides_pdf(project_id: str, actor: str = "system") -> Dict[str, Any]:
    """
    Export slides project as PDF presentation.

    Note: Actual PDF generation requires reportlab or similar library.
    """
    proj = get_project(project_id)
    if not proj:
        return {"ok": False, "error": "Project not found"}

    if proj.projectType != "slides":
        return {"ok": False, "error": "Project is not a slides project"}

    assets = list_assets(project_id)

    log_event(
        project_id,
        "export_slides_pdf",
        {"assetCount": len(assets)},
        actor=actor
    )

    slides_data = {
        "title": proj.title,
        "description": proj.description,
        "canvas": proj.canvas.model_dump(),
        "slides": [],
    }

    for i, asset in enumerate(assets):
        slides_data["slides"].append({
            "index": i + 1,
            "imageUrl": asset.url,
            "filename": asset.filename,
        })

    return {
        "ok": True,
        "projectId": project_id,
        "kind": "slides_pdf",
        "status": "data_ready",
        "data": slides_data,
        "filename": f"{proj.title.replace(' ', '_')}_slides.pdf",
        "message": "PDF generation ready. Use /studio/projects/{id}/export/slides-pdf to download.",
    }


def export_project_slides_pptx(project_id: str, actor: str = "system") -> Dict[str, Any]:
    """
    Export slides project as PowerPoint presentation.

    Note: Actual PPTX generation requires python-pptx library.
    """
    proj = get_project(project_id)
    if not proj:
        return {"ok": False, "error": "Project not found"}

    if proj.projectType != "slides":
        return {"ok": False, "error": "Project is not a slides project"}

    assets = list_assets(project_id)

    log_event(
        project_id,
        "export_slides_pptx",
        {"assetCount": len(assets)},
        actor=actor
    )

    # MVP: Return structure for PPTX generation
    # Production: Use python-pptx to generate actual file
    pptx_data = {
        "title": proj.title,
        "description": proj.description,
        "canvas": proj.canvas.model_dump(),
        "slides": [],
    }

    for i, asset in enumerate(assets):
        pptx_data["slides"].append({
            "index": i + 1,
            "imageUrl": asset.url,
            "filename": asset.filename,
        })

    return {
        "ok": True,
        "projectId": project_id,
        "kind": "slides_pptx",
        "status": "data_ready",
        "data": pptx_data,
        "filename": f"{proj.title.replace(' ', '_')}_slides.pptx",
        "message": "PPTX generation ready. Use /studio/projects/{id}/export/slides-pptx to download.",
    }


def export_project_assets_zip(project_id: str, actor: str = "system") -> Dict[str, Any]:
    """
    Export all project assets as a ZIP file.

    Returns ZIP file bytes or download URL.
    """
    proj = get_project(project_id)
    if not proj:
        return {"ok": False, "error": "Project not found"}

    assets = list_assets(project_id)

    log_event(
        project_id,
        "export_assets_zip",
        {"assetCount": len(assets)},
        actor=actor
    )

    # MVP: Return asset manifest for ZIP creation
    # Production: Create actual ZIP file with fetched assets
    manifest = {
        "project": {
            "id": proj.id,
            "title": proj.title,
            "projectType": proj.projectType,
        },
        "assets": [],
    }

    for asset in assets:
        manifest["assets"].append({
            "id": asset.id,
            "kind": asset.kind,
            "filename": asset.filename,
            "mime": asset.mime,
            "sizeBytes": asset.sizeBytes,
            "url": asset.url,
        })

    return {
        "ok": True,
        "projectId": project_id,
        "kind": "zip_assets",
        "status": "data_ready",
        "manifest": manifest,
        "filename": f"{proj.title.replace(' ', '_')}_assets.zip",
        "message": "ZIP creation ready. Use /studio/projects/{id}/export/zip to download.",
    }


def get_project_available_exports(project_id: str) -> Dict[str, Any]:
    """Get list of available export formats for a professional project."""
    proj = get_project(project_id)
    if not proj:
        return {"ok": False, "error": "Project not found"}

    is_slides = proj.projectType == "slides"

    exports = [
        {"kind": "json_metadata", "label": "Metadata (JSON)", "available": True},
        {"kind": "storyboard_pdf", "label": "Storyboard (PDF)", "available": True},
        {"kind": "zip_assets", "label": "Asset Pack (ZIP)", "available": True},
        {"kind": "slides_pdf", "label": "Slides (PDF)", "available": is_slides},
        {"kind": "slides_pptx", "label": "Slides (PowerPoint)", "available": is_slides},
    ]

    return {
        "ok": True,
        "projectId": project_id,
        "projectType": proj.projectType,
        "exports": [e for e in exports if e["available"]],
        "contentRating": proj.contentRating,
    }


def export_project(
    project_id: str,
    kind: str = "json_metadata",
    actor: str = "system"
) -> Dict[str, Any]:
    """
    Export professional project in specified format.

    Args:
        project_id: The project ID
        kind: Export type (json_metadata, storyboard_pdf, slides_pdf, slides_pptx, zip_assets)
        actor: User/system requesting export

    Returns:
        Export result with status and data/download info
    """
    exporters = {
        "json_metadata": export_project_json,
        "storyboard_pdf": export_project_storyboard_pdf,
        "slides_pdf": export_project_slides_pdf,
        "slides_pptx": export_project_slides_pptx,
        "zip_assets": export_project_assets_zip,
    }

    exporter = exporters.get(kind)
    if not exporter:
        return {"ok": False, "error": f"Unknown export kind: {kind}"}

    return exporter(project_id, actor=actor)
