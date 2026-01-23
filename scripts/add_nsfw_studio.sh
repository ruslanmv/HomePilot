#!/usr/bin/env bash
###############################################################################
# add_nsfw_studio.sh
#
# Additive-only script to create Studio module with optional NSFW governance
# for HomePilot. Creates YouTube-first workflow with enterprise-style mature
# content handling (not targeting adult platforms).
#
# Usage: ./scripts/add_nsfw_studio.sh [ROOT_DIR]
#        ROOT_DIR defaults to current directory
#
# This script is idempotent - safe to run multiple times.
###############################################################################
set -euo pipefail

ROOT="${1:-.}"

echo "=============================================="
echo "HomePilot Studio + NSFW Governance Generator"
echo "=============================================="
echo ""
echo "Target directory: $ROOT"
echo ""

# Helper: create directory and write file
write_file() {
  local path="$1"
  mkdir -p "$(dirname "$ROOT/$path")"
  cat > "$ROOT/$path"
  echo "  [+] $path"
}

###############################################################################
# BACKEND: Studio Module
###############################################################################
echo "[1/2] Creating backend Studio module..."
echo ""

# ----------------------------
# backend/app/studio/__init__.py
# ----------------------------
write_file "backend/app/studio/__init__.py" <<'PYEOF'
"""
Studio module (enterprise-style):
- YouTube + presentations workflow
- Optional Mature content handling with policy gating
- Audit trail hooks

Additive only: mount in main app by importing router.

Usage:
    from app.studio.routes import router as studio_router
    app.include_router(studio_router)

Enterprise Mature gate: set env STUDIO_ALLOW_MATURE=1 to allow mature mode.
"""

from .routes import router

__all__ = ["router"]
PYEOF

# ----------------------------
# backend/app/studio/models.py
# ----------------------------
write_file "backend/app/studio/models.py" <<'PYEOF'
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
PYEOF

# ----------------------------
# backend/app/studio/policy.py
# ----------------------------
write_file "backend/app/studio/policy.py" <<'PYEOF'
"""
NSFW Policy Engine for Studio.

Implements enterprise-grade content governance:
- SFW mode: Blocks explicit sexual content
- Mature mode: Allows artistic/educational mature themes
- Always blocks illegal/harmful content (CSAM, etc.)

This is NOT for adult platform integration. It's for legitimate
use cases like horror, medical education, fashion, art, etc.
"""
from __future__ import annotations

import os
import re
from typing import List

from .models import PolicyDecision, ContentRating, PolicyMode, ProviderPolicy

# ============================================================================
# Blocklists (simple v1 - enterprise should use ML classifiers)
# ============================================================================

# SFW blocklist: explicit sexual content
DEFAULT_SFW_BLOCKLIST = [
    r"\bexplicit\s+sex\b",
    r"\bporn\b",
    r"\bfuck\b",
    r"\bblowjob\b",
    r"\bpenetrat",
    r"\bincest\b",
    r"\brape\b",
    r"\bchild\b.*\bsex\b",
    r"\bnude\b.*\bchild\b",
    r"\bsexual\b.*\bminor\b",
]

# Absolute blocklist: never allowed even in mature mode (safety baseline)
ABSOLUTE_BLOCKLIST = [
    r"\bchild\b.*\b(nude|sex|porn)\b",
    r"\bminor\b.*\b(nude|sex|porn)\b",
    r"\bloli\b",
    r"\bshota\b",
    r"\bincest\b",
    r"\brape\b",
    r"\bcsam\b",
    r"\bpedophil",
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


_SFW_RE = _compile_patterns(DEFAULT_SFW_BLOCKLIST)
_ABSOLUTE_RE = _compile_patterns(ABSOLUTE_BLOCKLIST)


def org_allows_mature() -> bool:
    """
    Check if organization-level policy allows mature content.

    Enterprise gate: requires explicit server-side enablement.
    Set env STUDIO_ALLOW_MATURE=1 to enable.
    """
    return os.getenv("STUDIO_ALLOW_MATURE", "0").strip() == "1"


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
    # ABSOLUTE SAFETY: Always block regardless of mode
    # ========================================================================
    for rx in _ABSOLUTE_RE:
        if rx.search(text):
            return PolicyDecision(
                allowed=False,
                reason="Blocked by absolute safety baseline (illegal/harmful content)",
                flags=["absolute_block", "safety_violation"]
            )

    # ========================================================================
    # SFW MODE: Block explicit sexual content
    # ========================================================================
    if content_rating == "sfw":
        for rx in _SFW_RE:
            if rx.search(text):
                return PolicyDecision(
                    allowed=False,
                    reason="Blocked by SFW policy (explicit content)",
                    flags=["sfw_block"]
                )

        # YouTube-safe mode could add further restrictions (gore limits, etc.)
        if policy_mode == "youtube_safe":
            # Add additional YouTube-specific checks here if needed
            pass

        return PolicyDecision(allowed=True, reason="Allowed (SFW)")

    # ========================================================================
    # MATURE MODE: Requires multiple layers of approval
    # ========================================================================

    # Gate 1: Organization must allow mature content
    if not org_allows_mature():
        return PolicyDecision(
            allowed=False,
            reason="Organization policy disables mature content",
            flags=["org_disallows_mature"]
        )

    # Gate 2: Project must explicitly enable mature generation
    if not provider_policy.allowMature:
        return PolicyDecision(
            allowed=False,
            reason="Project provider policy disallows mature generation",
            flags=["project_disallows_mature"]
        )

    # Gate 3: Provider must be in allowlist
    allowed_providers = set(provider_policy.allowedProviders or [])
    if provider not in allowed_providers:
        return PolicyDecision(
            allowed=False,
            reason=f"Provider '{provider}' not in allowed providers: {allowed_providers}",
            flags=["provider_not_allowed"]
        )

    # Gate 4: Local-only enforcement if configured
    if provider_policy.localOnly and provider != "ollama":
        return PolicyDecision(
            allowed=False,
            reason="Mature mode requires local-only provider (ollama)",
            flags=["local_only_violation"]
        )

    return PolicyDecision(
        allowed=True,
        reason="Allowed (Mature - all gates passed)",
        flags=["mature_allowed"]
    )


def get_policy_summary(content_rating: ContentRating, provider_policy: ProviderPolicy) -> dict:
    """Get human-readable policy summary for UI display."""
    return {
        "contentRating": content_rating,
        "orgAllowsMature": org_allows_mature(),
        "projectAllowsMature": provider_policy.allowMature,
        "allowedProviders": provider_policy.allowedProviders,
        "localOnly": provider_policy.localOnly,
        "restrictions": [
            "No illegal/harmful content (always enforced)",
            "No explicit sexual content" if content_rating == "sfw" else "Mature themes allowed with gating",
            "Local providers only" if provider_policy.localOnly else "External providers allowed",
        ]
    }
PYEOF

# ----------------------------
# backend/app/studio/audit.py
# ----------------------------
write_file "backend/app/studio/audit.py" <<'PYEOF'
"""
Audit logging for Studio content governance.

Tracks all policy decisions and content generation for compliance.
In production, replace in-memory store with persistent database.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from .models import AuditEvent

# In-memory audit store (replace with DB in production)
_AUDIT_STORE: List[AuditEvent] = []


def log_event(
    video_id: str,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    actor: str = "system"
) -> AuditEvent:
    """
    Log an audit event.

    Args:
        video_id: The video project ID
        event_type: Type of event (e.g., create_video, policy_check, generation)
        payload: Additional event data
        actor: Who triggered the event (user ID or "system")

    Returns:
        The created AuditEvent
    """
    evt = AuditEvent(
        eventId=str(uuid.uuid4()),
        videoId=video_id,
        actor=actor,
        type=event_type,
        payload=payload or {},
        timestamp=time.time(),
    )
    _AUDIT_STORE.append(evt)
    return evt


def list_events(
    video_id: str,
    event_type: Optional[str] = None,
    limit: int = 100
) -> List[AuditEvent]:
    """
    List audit events for a video.

    Args:
        video_id: The video project ID
        event_type: Optional filter by event type
        limit: Maximum number of events to return

    Returns:
        List of matching AuditEvents, most recent first
    """
    events = [e for e in _AUDIT_STORE if e.videoId == video_id]

    if event_type:
        events = [e for e in events if e.type == event_type]

    # Sort by timestamp descending (most recent first)
    events.sort(key=lambda x: x.timestamp, reverse=True)

    return events[:limit]


def get_policy_violations(video_id: str) -> List[AuditEvent]:
    """Get all policy violation events for a video."""
    events = list_events(video_id, event_type="policy_check")
    return [e for e in events if not e.payload.get("allowed", True)]


def clear_events(video_id: str) -> int:
    """Clear all audit events for a video. Returns count of deleted events."""
    global _AUDIT_STORE
    before = len(_AUDIT_STORE)
    _AUDIT_STORE = [e for e in _AUDIT_STORE if e.videoId != video_id]
    return before - len(_AUDIT_STORE)
PYEOF

# ----------------------------
# backend/app/studio/repo.py
# ----------------------------
write_file "backend/app/studio/repo.py" <<'PYEOF'
"""
Repository layer for Studio video projects.

In-memory storage for MVP. Replace with proper database in production.
"""
from __future__ import annotations

import time
import uuid
from typing import Dict, List, Optional

from .models import StudioVideo, StudioVideoCreate

# In-memory store (replace with DB in production)
_VIDEO_STORE: Dict[str, StudioVideo] = {}


def create_video(inp: StudioVideoCreate) -> StudioVideo:
    """Create a new video project."""
    now = time.time()
    vid = StudioVideo(
        id=str(uuid.uuid4()),
        title=inp.title,
        logline=inp.logline or "",
        tags=inp.tags or [],
        status="draft",
        platformPreset=inp.platformPreset,
        targetDurationSec=inp.targetDurationSec or 180,
        contentRating=inp.contentRating,
        policyMode=inp.policyMode,
        providerPolicy=inp.providerPolicy,
        createdAt=now,
        updatedAt=now,
    )
    _VIDEO_STORE[vid.id] = vid
    return vid


def list_videos(
    q: Optional[str] = None,
    status: Optional[str] = None,
    preset: Optional[str] = None,
    contentRating: Optional[str] = None,
    limit: int = 100,
) -> List[StudioVideo]:
    """
    List video projects with optional filters.

    Args:
        q: Search query (matches title and logline)
        status: Filter by status
        preset: Filter by platform preset
        contentRating: Filter by content rating
        limit: Maximum number of results

    Returns:
        List of matching videos, sorted by updatedAt desc
    """
    items = list(_VIDEO_STORE.values())

    if q:
        ql = q.lower()
        items = [v for v in items if ql in v.title.lower() or ql in (v.logline or "").lower()]

    if status:
        items = [v for v in items if v.status == status]

    if preset:
        items = [v for v in items if v.platformPreset == preset]

    if contentRating:
        items = [v for v in items if v.contentRating == contentRating]

    # Sort by updatedAt descending
    items.sort(key=lambda x: x.updatedAt, reverse=True)

    return items[:limit]


def get_video(video_id: str) -> Optional[StudioVideo]:
    """Get a video by ID."""
    return _VIDEO_STORE.get(video_id)


def update_video(video_id: str, **updates) -> Optional[StudioVideo]:
    """Update a video's fields."""
    v = _VIDEO_STORE.get(video_id)
    if not v:
        return None

    for key, value in updates.items():
        if hasattr(v, key):
            setattr(v, key, value)

    v.updatedAt = time.time()
    _VIDEO_STORE[video_id] = v
    return v


def touch(video_id: str) -> None:
    """Update the video's updatedAt timestamp."""
    v = _VIDEO_STORE.get(video_id)
    if v:
        v.updatedAt = time.time()
        _VIDEO_STORE[video_id] = v


def delete_video(video_id: str) -> bool:
    """Delete a video. Returns True if deleted."""
    if video_id in _VIDEO_STORE:
        del _VIDEO_STORE[video_id]
        return True
    return False
PYEOF

# ----------------------------
# backend/app/studio/service.py
# ----------------------------
write_file "backend/app/studio/service.py" <<'PYEOF'
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
PYEOF

# ----------------------------
# backend/app/studio/exporter.py
# ----------------------------
write_file "backend/app/studio/exporter.py" <<'PYEOF'
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
PYEOF

# ----------------------------
# backend/app/studio/routes.py
# ----------------------------
write_file "backend/app/studio/routes.py" <<'PYEOF'
"""
FastAPI routes for Studio module.

Mount this router in your main app:
    from app.studio import router as studio_router
    app.include_router(studio_router)
"""
from __future__ import annotations

from fastapi import APIRouter, Query, HTTPException
from typing import Optional

from .models import StudioVideoCreate, GenerationRequest, ExportRequest
from .repo import list_videos, get_video
from .service import (
    create,
    policy_check_generation,
    get_video_policy_summary,
    update_content_rating,
)
from .audit import list_events, get_policy_violations
from .exporter import export_pack, get_available_exports

router = APIRouter(prefix="/studio", tags=["studio"])


# ============================================================================
# Video CRUD
# ============================================================================

@router.get("/videos")
def videos_list(
    q: Optional[str] = Query(default=None, description="Search query"),
    status: Optional[str] = Query(default=None, description="Filter by status"),
    preset: Optional[str] = Query(default=None, description="Filter by platform preset"),
    contentRating: Optional[str] = Query(default=None, description="Filter by content rating"),
):
    """List all video projects with optional filters."""
    vids = list_videos(q=q, status=status, preset=preset, contentRating=contentRating)
    return {"videos": [v.model_dump() for v in vids]}


@router.post("/videos")
def video_create(inp: StudioVideoCreate):
    """Create a new video project."""
    v = create(inp)
    return {"video": v.model_dump()}


@router.get("/videos/{video_id}")
def video_detail(video_id: str):
    """Get video project details."""
    v = get_video(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")
    return {"video": v.model_dump()}


# ============================================================================
# Policy
# ============================================================================

@router.get("/videos/{video_id}/policy")
def video_policy(video_id: str):
    """Get policy summary for a video project."""
    summary = get_video_policy_summary(video_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Video not found")
    return {"policy": summary}


@router.post("/videos/{video_id}/policy/check")
def policy_check(video_id: str, req: GenerationRequest):
    """
    Check if a generation prompt is allowed by policy.

    Use this before generating content to verify compliance.
    """
    result = policy_check_generation(
        video_id=video_id,
        prompt=req.prompt,
        provider=req.provider,
    )
    return result


@router.patch("/videos/{video_id}/content-rating")
def update_rating(video_id: str, contentRating: str = Query(...)):
    """Update video content rating (sfw or mature)."""
    if contentRating not in ("sfw", "mature"):
        raise HTTPException(status_code=400, detail="Invalid content rating")

    v = update_content_rating(video_id, contentRating)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")
    return {"video": v.model_dump()}


# ============================================================================
# Audit
# ============================================================================

@router.get("/videos/{video_id}/audit")
def audit_log(
    video_id: str,
    event_type: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=500),
):
    """Get audit log for a video project."""
    events = list_events(video_id, event_type=event_type, limit=limit)
    return {"events": [e.model_dump() for e in events]}


@router.get("/videos/{video_id}/policy-violations")
def policy_violations(video_id: str):
    """Get policy violation events for a video."""
    violations = get_policy_violations(video_id)
    return {"violations": [v.model_dump() for v in violations]}


# ============================================================================
# Export
# ============================================================================

@router.get("/videos/{video_id}/exports")
def available_exports(video_id: str):
    """Get available export formats for a video."""
    return get_available_exports(video_id)


@router.post("/videos/{video_id}/export")
def do_export(video_id: str, req: ExportRequest):
    """Export video project assets."""
    return export_pack(video_id, kind=req.kind)


# ============================================================================
# Health
# ============================================================================

@router.get("/health")
def health():
    """Studio module health check."""
    return {"status": "ok", "module": "studio"}
PYEOF

echo ""

###############################################################################
# FRONTEND: Studio Shell Components
###############################################################################
echo "[2/2] Creating frontend Studio components..."
echo ""

# ----------------------------
# frontend/src/ui/studio/StudioRoutes.tsx
# ----------------------------
write_file "frontend/src/ui/studio/StudioRoutes.tsx" <<'TSXEOF'
import React from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { StudioHome } from "./pages/StudioHome";
import { StudioNewWizard } from "./pages/StudioNewWizard";
import { StudioWorkspace } from "./pages/StudioWorkspace";

/**
 * Studio routing configuration.
 *
 * Routes:
 * - /studio         → Library home
 * - /studio/new     → New project wizard
 * - /studio/videos/:id/* → Video workspace with tabs
 */
export function StudioRoutes() {
  return (
    <Routes>
      <Route path="/" element={<StudioHome />} />
      <Route path="/new" element={<StudioNewWizard />} />
      <Route path="/videos/:id/*" element={<StudioWorkspace />} />
      <Route path="*" element={<Navigate to="/studio" replace />} />
    </Routes>
  );
}
TSXEOF

# ----------------------------
# frontend/src/ui/studio/StudioShell.tsx
# ----------------------------
write_file "frontend/src/ui/studio/StudioShell.tsx" <<'TSXEOF'
import React from "react";
import { ContentRatingBadge } from "./components/ContentRatingBadge";
import { StatusBadge } from "./components/StatusBadge";
import { PlatformBadge } from "./components/PlatformBadge";

type Props = {
  title: string;
  status?: "draft" | "in_review" | "approved" | "archived";
  platformPreset?: "youtube_16_9" | "shorts_9_16" | "slides_16_9";
  contentRating?: "sfw" | "mature";
  rightActions?: React.ReactNode;
  children: React.ReactNode;
};

/**
 * Studio shell layout with header and content area.
 *
 * Header shows:
 * - Breadcrumb (Studio / {title})
 * - Status badge
 * - Platform preset badge
 * - Content rating badge (NSFW indicator)
 * - Right-side actions slot
 */
export function StudioShell(props: Props) {
  const {
    title,
    status = "draft",
    platformPreset = "youtube_16_9",
    contentRating = "sfw",
  } = props;

  return (
    <div className="h-full w-full grid" style={{ gridTemplateRows: "56px 1fr" }}>
      {/* Header bar */}
      <header className="flex items-center justify-between px-4 border-b bg-background">
        <div className="flex items-center gap-3 min-w-0">
          <div className="text-sm opacity-70">Studio</div>
          <div className="text-sm opacity-40">/</div>
          <div className="font-semibold truncate">{title}</div>
          <StatusBadge status={status} />
          <PlatformBadge preset={platformPreset} />
          <ContentRatingBadge value={contentRating} />
        </div>
        <div className="flex items-center gap-2">{props.rightActions}</div>
      </header>

      {/* Main content */}
      <main className="h-full w-full overflow-auto">{props.children}</main>
    </div>
  );
}
TSXEOF

# ----------------------------
# frontend/src/ui/studio/StudioLibraryRail.tsx
# ----------------------------
write_file "frontend/src/ui/studio/StudioLibraryRail.tsx" <<'TSXEOF'
import React from "react";

export type LibraryFilter = {
  q: string;
  status?: string;
  preset?: string;
  contentRating?: string;
};

type Props = {
  filter: LibraryFilter;
  onChange: (f: LibraryFilter) => void;
  collapsed?: boolean;
  children?: React.ReactNode;
};

/**
 * Left sidebar library rail with filters.
 *
 * Filters:
 * - Search (title, tags, owner)
 * - Status (draft, in_review, approved, archived)
 * - Platform preset
 * - Content rating (SFW only / Mature allowed)
 */
export function StudioLibraryRail(props: Props) {
  const { filter: f, collapsed = false } = props;

  if (collapsed) {
    return (
      <div className="h-full w-[72px] border-r bg-background flex flex-col items-center py-3">
        <div className="text-xs opacity-70 writing-vertical">Library</div>
      </div>
    );
  }

  return (
    <div className="h-full w-[320px] border-r bg-background flex flex-col">
      <div className="p-3 border-b">
        <div className="font-semibold mb-2">Library</div>

        {/* Search input */}
        <input
          className="w-full border rounded px-2 py-1 text-sm"
          placeholder="Search title, tag, owner..."
          value={f.q}
          onChange={(e) => props.onChange({ ...f, q: e.target.value })}
        />

        {/* Filter dropdowns */}
        <div className="grid grid-cols-2 gap-2 mt-2">
          <select
            className="border rounded px-2 py-1 text-sm"
            value={f.status || ""}
            onChange={(e) =>
              props.onChange({ ...f, status: e.target.value || undefined })
            }
          >
            <option value="">Status</option>
            <option value="draft">Draft</option>
            <option value="in_review">In Review</option>
            <option value="approved">Approved</option>
            <option value="archived">Archived</option>
          </select>

          <select
            className="border rounded px-2 py-1 text-sm"
            value={f.preset || ""}
            onChange={(e) =>
              props.onChange({ ...f, preset: e.target.value || undefined })
            }
          >
            <option value="">Preset</option>
            <option value="youtube_16_9">YouTube 16:9</option>
            <option value="shorts_9_16">Shorts 9:16</option>
            <option value="slides_16_9">Slides 16:9</option>
          </select>

          {/* Content rating filter - NSFW governance */}
          <select
            className="border rounded px-2 py-1 text-sm col-span-2"
            value={f.contentRating || ""}
            onChange={(e) =>
              props.onChange({ ...f, contentRating: e.target.value || undefined })
            }
          >
            <option value="">Content Rating</option>
            <option value="sfw">SFW only</option>
            <option value="mature">Mature allowed</option>
          </select>
        </div>
      </div>

      {/* Video list slot */}
      <div className="flex-1 overflow-auto">{props.children}</div>
    </div>
  );
}
TSXEOF

# ----------------------------
# frontend/src/ui/studio/components/ContentRatingBadge.tsx
# ----------------------------
write_file "frontend/src/ui/studio/components/ContentRatingBadge.tsx" <<'TSXEOF'
import React from "react";

type Props = {
  value: "sfw" | "mature";
  showLabel?: boolean;
};

/**
 * Badge showing content rating (SFW or Mature).
 *
 * Mature badge has warning styling (yellow/amber).
 */
export function ContentRatingBadge({ value, showLabel = true }: Props) {
  if (value === "mature") {
    return (
      <span
        className="text-xs px-2 py-1 rounded-full border border-yellow-500/50 bg-yellow-500/10 text-yellow-600 dark:text-yellow-400"
        title="Mature content enabled - exports may have restrictions"
      >
        {showLabel ? "Mature" : "M"}
      </span>
    );
  }

  return (
    <span
      className="text-xs px-2 py-1 rounded-full border opacity-80"
      title="Safe for work content"
    >
      {showLabel ? "SFW" : "S"}
    </span>
  );
}
TSXEOF

# ----------------------------
# frontend/src/ui/studio/components/StatusBadge.tsx
# ----------------------------
write_file "frontend/src/ui/studio/components/StatusBadge.tsx" <<'TSXEOF'
import React from "react";

type Status = "draft" | "in_review" | "approved" | "archived";

const STATUS_CONFIG: Record<Status, { label: string; className: string }> = {
  draft: {
    label: "Draft",
    className: "border-gray-500/50 bg-gray-500/10",
  },
  in_review: {
    label: "In Review",
    className: "border-blue-500/50 bg-blue-500/10 text-blue-600 dark:text-blue-400",
  },
  approved: {
    label: "Approved",
    className: "border-green-500/50 bg-green-500/10 text-green-600 dark:text-green-400",
  },
  archived: {
    label: "Archived",
    className: "border-gray-500/50 bg-gray-500/10 opacity-60",
  },
};

export function StatusBadge({ status }: { status: Status }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.draft;

  return (
    <span className={`text-xs px-2 py-1 rounded-full border ${config.className}`}>
      {config.label}
    </span>
  );
}
TSXEOF

# ----------------------------
# frontend/src/ui/studio/components/PlatformBadge.tsx
# ----------------------------
write_file "frontend/src/ui/studio/components/PlatformBadge.tsx" <<'TSXEOF'
import React from "react";

type Preset = "youtube_16_9" | "shorts_9_16" | "slides_16_9";

const PRESET_CONFIG: Record<Preset, { label: string; icon: string }> = {
  youtube_16_9: { label: "YouTube 16:9", icon: "▶" },
  shorts_9_16: { label: "Shorts 9:16", icon: "📱" },
  slides_16_9: { label: "Slides 16:9", icon: "📊" },
};

export function PlatformBadge({ preset }: { preset: Preset }) {
  const config = PRESET_CONFIG[preset] || PRESET_CONFIG.youtube_16_9;

  return (
    <span className="text-xs px-2 py-1 rounded-full border opacity-80">
      {config.icon} {config.label}
    </span>
  );
}
TSXEOF

# ----------------------------
# frontend/src/ui/studio/components/PolicyBanner.tsx
# ----------------------------
write_file "frontend/src/ui/studio/components/PolicyBanner.tsx" <<'TSXEOF'
import React from "react";

type Props = {
  contentRating: "sfw" | "mature";
  restrictions?: string[];
  onDismiss?: () => void;
};

/**
 * Banner showing policy status and restrictions.
 * Shows warning when Mature content is enabled.
 */
export function PolicyBanner({ contentRating, restrictions = [], onDismiss }: Props) {
  if (contentRating !== "mature") {
    return null;
  }

  return (
    <div className="mx-4 my-2 p-3 border rounded bg-yellow-500/10 border-yellow-500/30">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold text-sm text-yellow-600 dark:text-yellow-400">
            ⚠️ Mature content enabled
          </div>
          <div className="text-xs opacity-80 mt-1">
            This project may generate sensitive imagery. Use only for permitted
            artistic/educational contexts. Exports may have restrictions.
          </div>
          {restrictions.length > 0 && (
            <ul className="text-xs opacity-70 mt-2 list-disc list-inside">
              {restrictions.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
        </div>
        {onDismiss && (
          <button
            onClick={onDismiss}
            className="text-xs opacity-50 hover:opacity-100"
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}
TSXEOF

# ----------------------------
# frontend/src/ui/studio/components/index.ts
# ----------------------------
write_file "frontend/src/ui/studio/components/index.ts" <<'TSEOF'
export { ContentRatingBadge } from "./ContentRatingBadge";
export { StatusBadge } from "./StatusBadge";
export { PlatformBadge } from "./PlatformBadge";
export { PolicyBanner } from "./PolicyBanner";
TSEOF

# ----------------------------
# frontend/src/ui/studio/pages/StudioHome.tsx
# ----------------------------
write_file "frontend/src/ui/studio/pages/StudioHome.tsx" <<'TSXEOF'
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { StudioLibraryRail, LibraryFilter } from "../StudioLibraryRail";
import { ContentRatingBadge } from "../components/ContentRatingBadge";

type Video = {
  id: string;
  title: string;
  logline: string;
  status: "draft" | "in_review" | "approved" | "archived";
  updatedAt: number;
  platformPreset: "youtube_16_9" | "shorts_9_16" | "slides_16_9";
  contentRating: "sfw" | "mature";
};

/**
 * Studio library home page.
 * Lists all video projects with search and filter.
 */
export function StudioHome() {
  const [filter, setFilter] = useState<LibraryFilter>({ q: "" });
  const [videos, setVideos] = useState<Video[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadVideos() {
    setLoading(true);
    setError(null);

    const params = new URLSearchParams();
    if (filter.q) params.set("q", filter.q);
    if (filter.status) params.set("status", filter.status);
    if (filter.preset) params.set("preset", filter.preset);
    if (filter.contentRating) params.set("contentRating", filter.contentRating);

    try {
      const r = await fetch(`/studio/videos?${params.toString()}`);
      const j = await r.json();
      if (!r.ok) throw new Error(j?.detail || j?.error || `HTTP ${r.status}`);
      setVideos(j.videos || []);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadVideos();
  }, [filter.q, filter.status, filter.preset, filter.contentRating]);

  return (
    <div className="h-full w-full flex">
      <StudioLibraryRail filter={filter} onChange={setFilter}>
        <div className="p-3 flex items-center justify-between border-b">
          <div className="text-sm opacity-70">Projects</div>
          <Link
            to="/studio/new"
            className="text-sm px-3 py-1 rounded border hover:bg-muted/30"
          >
            + New
          </Link>
        </div>

        {error && (
          <div className="mx-3 my-2 text-sm p-2 border rounded bg-red-500/10 border-red-500/30">
            {error}
          </div>
        )}

        {loading && (
          <div className="p-3 text-sm opacity-70">Loading...</div>
        )}

        <div className="px-3 pb-6 grid gap-2">
          {videos.map((v) => (
            <Link
              key={v.id}
              to={`/studio/videos/${v.id}/overview`}
              className="border rounded p-3 hover:bg-muted/30 transition-colors"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="font-semibold truncate flex-1">{v.title}</div>
                <ContentRatingBadge value={v.contentRating} showLabel={false} />
              </div>
              {v.logline && (
                <div className="text-xs opacity-70 mt-1 line-clamp-2">
                  {v.logline}
                </div>
              )}
              <div className="text-xs opacity-50 mt-2 flex gap-2">
                <span className="capitalize">{v.status.replace("_", " ")}</span>
                <span>•</span>
                <span>{v.platformPreset.replace(/_/g, " ")}</span>
              </div>
            </Link>
          ))}

          {!loading && !videos.length && !error && (
            <div className="text-sm opacity-70 p-4 border rounded text-center">
              No projects yet.
              <br />
              <Link to="/studio/new" className="underline">
                Create your first project
              </Link>
            </div>
          )}
        </div>
      </StudioLibraryRail>

      <div className="flex-1 flex items-center justify-center bg-muted/10">
        <div className="text-center">
          <div className="text-lg font-semibold mb-2">Studio</div>
          <div className="text-sm opacity-70">
            Select a project or create a new one.
          </div>
        </div>
      </div>
    </div>
  );
}
TSXEOF

# ----------------------------
# frontend/src/ui/studio/pages/StudioNewWizard.tsx
# ----------------------------
write_file "frontend/src/ui/studio/pages/StudioNewWizard.tsx" <<'TSXEOF'
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";

type PlatformPreset = "youtube_16_9" | "shorts_9_16" | "slides_16_9";
type ContentRating = "sfw" | "mature";

/**
 * New project creation wizard.
 *
 * Steps:
 * 1. Basic info (title, logline)
 * 2. Format (platform preset)
 * 3. Policy & Safety (content rating, provider policy)
 */
export function StudioNewWizard() {
  const nav = useNavigate();

  // Form state
  const [title, setTitle] = useState("");
  const [logline, setLogline] = useState("");
  const [platformPreset, setPlatformPreset] = useState<PlatformPreset>("youtube_16_9");
  const [contentRating, setContentRating] = useState<ContentRating>("sfw");
  const [allowMature, setAllowMature] = useState(false);
  const [localOnly, setLocalOnly] = useState(true);

  // UI state
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreate() {
    if (!title.trim()) {
      setError("Title is required");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const r = await fetch("/studio/videos", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: title.trim(),
          logline: logline.trim(),
          platformPreset,
          contentRating,
          policyMode: contentRating === "mature" ? "restricted" : "youtube_safe",
          providerPolicy: {
            allowMature: contentRating === "mature" ? allowMature : false,
            allowedProviders: ["ollama"],
            localOnly,
          },
        }),
      });

      const j = await r.json();
      if (!r.ok) throw new Error(j?.detail || j?.error || `HTTP ${r.status}`);

      nav(`/studio/videos/${j.video.id}/overview`);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  const matureDisabled = contentRating !== "mature";

  return (
    <div className="h-full w-full flex items-center justify-center p-6">
      <div className="w-full max-w-xl border rounded p-6 bg-background">
        <div className="text-xl font-semibold">New Studio Project</div>
        <div className="text-sm opacity-70 mt-1">
          YouTube-first workflow with optional mature content governance.
        </div>

        <div className="mt-6 grid gap-4">
          {/* Title */}
          <div>
            <label className="text-sm font-medium mb-1 block">Title *</label>
            <input
              className="w-full border rounded px-3 py-2"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g., Product Launch Teaser"
            />
          </div>

          {/* Logline */}
          <div>
            <label className="text-sm font-medium mb-1 block">Logline</label>
            <textarea
              className="w-full border rounded px-3 py-2 resize-none"
              rows={2}
              value={logline}
              onChange={(e) => setLogline(e.target.value)}
              placeholder="Brief description of your video..."
            />
          </div>

          {/* Platform preset */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium mb-1 block">Platform</label>
              <select
                className="w-full border rounded px-3 py-2"
                value={platformPreset}
                onChange={(e) => setPlatformPreset(e.target.value as PlatformPreset)}
              >
                <option value="youtube_16_9">YouTube 16:9</option>
                <option value="shorts_9_16">Shorts 9:16</option>
                <option value="slides_16_9">Slides 16:9</option>
              </select>
            </div>

            {/* Content rating */}
            <div>
              <label className="text-sm font-medium mb-1 block">
                Content Rating
              </label>
              <select
                className="w-full border rounded px-3 py-2"
                value={contentRating}
                onChange={(e) => setContentRating(e.target.value as ContentRating)}
              >
                <option value="sfw">SFW (Safe for Work)</option>
                <option value="mature">Mature</option>
              </select>
            </div>
          </div>

          {/* Policy & Safety section */}
          <div className="border rounded p-4 mt-2">
            <div className="font-semibold text-sm">Policy & Safety</div>
            <div className="text-xs opacity-70 mt-1">
              Mature content is intended for permitted artistic/educational
              contexts (horror, medical, fashion, etc.). Organization must enable
              it server-side via <code>STUDIO_ALLOW_MATURE=1</code>.
            </div>

            <div className="mt-3 grid gap-2">
              <label
                className={`flex items-center gap-2 text-sm ${
                  matureDisabled ? "opacity-50 cursor-not-allowed" : ""
                }`}
              >
                <input
                  type="checkbox"
                  disabled={matureDisabled}
                  checked={allowMature}
                  onChange={(e) => setAllowMature(e.target.checked)}
                />
                Allow mature generation (project-level)
              </label>

              <label
                className={`flex items-center gap-2 text-sm ${
                  matureDisabled ? "opacity-50 cursor-not-allowed" : ""
                }`}
              >
                <input
                  type="checkbox"
                  disabled={matureDisabled}
                  checked={localOnly}
                  onChange={(e) => setLocalOnly(e.target.checked)}
                />
                Local-only mode (recommended for mature content)
              </label>

              <div className="text-xs opacity-60 mt-1">
                Default allowed providers: <code>ollama</code> (local)
              </div>
            </div>

            {contentRating === "mature" && (
              <div className="mt-3 p-2 bg-yellow-500/10 border border-yellow-500/30 rounded text-xs">
                ⚠️ This project may generate sensitive imagery. Use only for
                permitted artistic/educational contexts.
              </div>
            )}
          </div>

          {/* Error */}
          {error && (
            <div className="text-sm p-3 border rounded bg-red-500/10 border-red-500/30">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-2 justify-end mt-2">
            <button
              className="px-4 py-2 rounded border hover:bg-muted/30"
              onClick={() => nav("/studio")}
              disabled={loading}
            >
              Cancel
            </button>
            <button
              className="px-4 py-2 rounded border bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
              onClick={handleCreate}
              disabled={!title.trim() || loading}
            >
              {loading ? "Creating..." : "Create Project"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
TSXEOF

# ----------------------------
# frontend/src/ui/studio/pages/StudioWorkspace.tsx
# ----------------------------
write_file "frontend/src/ui/studio/pages/StudioWorkspace.tsx" <<'TSXEOF'
import React, { useEffect, useState } from "react";
import { useParams, Routes, Route, Navigate, NavLink } from "react-router-dom";
import { StudioShell } from "../StudioShell";
import { PolicyBanner } from "../components/PolicyBanner";

// Tab components (stubs for now)
import { OverviewTab } from "../tabs/OverviewTab";
import { BibleTab } from "../tabs/BibleTab";
import { TimelineTab } from "../tabs/TimelineTab";
import { PlayerTab } from "../tabs/PlayerTab";
import { ExportTab } from "../tabs/ExportTab";
import { ActivityTab } from "../tabs/ActivityTab";

type Video = {
  id: string;
  title: string;
  logline: string;
  status: "draft" | "in_review" | "approved" | "archived";
  platformPreset: "youtube_16_9" | "shorts_9_16" | "slides_16_9";
  contentRating: "sfw" | "mature";
};

function TabBar({ id }: { id: string }) {
  const tabs = [
    { to: `/studio/videos/${id}/overview`, label: "Overview" },
    { to: `/studio/videos/${id}/bible`, label: "Channel Bible" },
    { to: `/studio/videos/${id}/timeline`, label: "Timeline" },
    { to: `/studio/videos/${id}/player`, label: "Player" },
    { to: `/studio/videos/${id}/export`, label: "Export" },
    { to: `/studio/videos/${id}/activity`, label: "Activity" },
  ];

  return (
    <div className="flex gap-1">
      {tabs.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          className={({ isActive }) =>
            `text-sm px-3 py-1 rounded border transition-colors ${
              isActive
                ? "bg-primary text-primary-foreground"
                : "hover:bg-muted/30"
            }`
          }
        >
          {t.label}
        </NavLink>
      ))}
    </div>
  );
}

/**
 * Video workspace with tabs.
 *
 * Tabs:
 * - Overview: KPIs, policy warnings
 * - Channel Bible: Brand guidelines, policy controls
 * - Timeline: Clip/scene editing (NSFW-aware generation)
 * - Player: Playback preview
 * - Export: Export packs (policy enforced)
 * - Activity: Audit log
 */
export function StudioWorkspace() {
  const { id } = useParams<{ id: string }>();
  const [video, setVideo] = useState<Video | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bannerDismissed, setBannerDismissed] = useState(false);

  useEffect(() => {
    if (!id) return;

    setLoading(true);
    setError(null);

    fetch(`/studio/videos/${id}`)
      .then((r) => r.json())
      .then((j) => {
        if (j.video) {
          setVideo(j.video);
        } else {
          setError(j.detail || j.error || "Video not found");
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  if (!id) {
    return <Navigate to="/studio" replace />;
  }

  if (loading) {
    return (
      <div className="h-full w-full flex items-center justify-center">
        <div className="text-sm opacity-70">Loading...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full w-full flex items-center justify-center">
        <div className="text-center">
          <div className="text-sm text-red-500">{error}</div>
          <a href="/studio" className="text-sm underline mt-2 inline-block">
            Back to Library
          </a>
        </div>
      </div>
    );
  }

  return (
    <StudioShell
      title={video?.title || "Untitled"}
      status={video?.status}
      platformPreset={video?.platformPreset}
      contentRating={video?.contentRating || "sfw"}
      rightActions={<TabBar id={id} />}
    >
      {/* Policy warning banner for mature content */}
      {!bannerDismissed && video?.contentRating === "mature" && (
        <PolicyBanner
          contentRating={video.contentRating}
          restrictions={[
            "Exports may require compliance confirmation",
            "Public sharing may be restricted",
          ]}
          onDismiss={() => setBannerDismissed(true)}
        />
      )}

      {/* Tab content */}
      <div className="h-full">
        <Routes>
          <Route path="overview" element={<OverviewTab video={video} />} />
          <Route path="bible" element={<BibleTab video={video} />} />
          <Route path="timeline" element={<TimelineTab video={video} />} />
          <Route path="player" element={<PlayerTab video={video} />} />
          <Route path="export" element={<ExportTab video={video} />} />
          <Route path="activity" element={<ActivityTab video={video} />} />
          <Route path="*" element={<Navigate to="overview" replace />} />
        </Routes>
      </div>
    </StudioShell>
  );
}
TSXEOF

# ----------------------------
# frontend/src/ui/studio/tabs/OverviewTab.tsx
# ----------------------------
write_file "frontend/src/ui/studio/tabs/OverviewTab.tsx" <<'TSXEOF'
import React, { useEffect, useState } from "react";

type Video = {
  id: string;
  title: string;
  logline: string;
  contentRating: "sfw" | "mature";
};

export function OverviewTab({ video }: { video: Video | null }) {
  const [policyViolations, setPolicyViolations] = useState<number>(0);

  useEffect(() => {
    if (!video?.id) return;

    fetch(`/studio/videos/${video.id}/policy-violations`)
      .then((r) => r.json())
      .then((j) => {
        setPolicyViolations(j.violations?.length || 0);
      })
      .catch(() => {});
  }, [video?.id]);

  if (!video) return null;

  return (
    <div className="p-6">
      <div className="text-lg font-semibold">Overview</div>
      <div className="text-sm opacity-70 mt-1">{video.logline || "No description"}</div>

      <div className="grid grid-cols-3 gap-4 mt-6">
        <div className="border rounded p-4">
          <div className="text-xs opacity-70">Status</div>
          <div className="text-lg font-semibold mt-1 capitalize">Draft</div>
        </div>

        <div className="border rounded p-4">
          <div className="text-xs opacity-70">Content Rating</div>
          <div className="text-lg font-semibold mt-1 capitalize">{video.contentRating}</div>
        </div>

        <div className="border rounded p-4">
          <div className="text-xs opacity-70">Policy Warnings</div>
          <div className={`text-lg font-semibold mt-1 ${policyViolations > 0 ? "text-yellow-600" : ""}`}>
            {policyViolations}
          </div>
        </div>
      </div>

      {video.contentRating === "mature" && (
        <div className="mt-6 p-4 border rounded bg-yellow-500/10 border-yellow-500/30">
          <div className="font-semibold text-sm">Mature Content Enabled</div>
          <div className="text-xs opacity-80 mt-1">
            This project allows mature themes. Generation requires provider approval.
            Exports may have restrictions.
          </div>
        </div>
      )}
    </div>
  );
}
TSXEOF

# ----------------------------
# frontend/src/ui/studio/tabs/BibleTab.tsx
# ----------------------------
write_file "frontend/src/ui/studio/tabs/BibleTab.tsx" <<'TSXEOF'
import React, { useState, useEffect } from "react";

type Video = {
  id: string;
  contentRating: "sfw" | "mature";
};

type PolicySummary = {
  contentRating: string;
  orgAllowsMature: boolean;
  projectAllowsMature: boolean;
  allowedProviders: string[];
  localOnly: boolean;
  restrictions: string[];
};

export function BibleTab({ video }: { video: Video | null }) {
  const [policy, setPolicy] = useState<PolicySummary | null>(null);

  useEffect(() => {
    if (!video?.id) return;

    fetch(`/studio/videos/${video.id}/policy`)
      .then((r) => r.json())
      .then((j) => setPolicy(j.policy))
      .catch(() => {});
  }, [video?.id]);

  if (!video) return null;

  return (
    <div className="p-6">
      <div className="text-lg font-semibold">Channel Bible</div>
      <div className="text-sm opacity-70 mt-1">
        Brand guidelines, tone, and policy controls.
      </div>

      <div className="grid grid-cols-2 gap-6 mt-6">
        {/* Left: Brand guidelines (stub) */}
        <div className="border rounded p-4">
          <div className="font-semibold text-sm">Brand Guidelines</div>
          <div className="text-xs opacity-70 mt-2">
            Coming soon: tone of voice, visual style, brand colors.
          </div>
        </div>

        {/* Right: Policy controls */}
        <div className="border rounded p-4">
          <div className="font-semibold text-sm">Policy Controls</div>

          {policy && (
            <div className="mt-3 grid gap-2 text-sm">
              <div className="flex justify-between">
                <span className="opacity-70">Content Rating:</span>
                <span className="capitalize">{policy.contentRating}</span>
              </div>

              <div className="flex justify-between">
                <span className="opacity-70">Org Allows Mature:</span>
                <span>{policy.orgAllowsMature ? "Yes" : "No"}</span>
              </div>

              <div className="flex justify-between">
                <span className="opacity-70">Project Allows Mature:</span>
                <span>{policy.projectAllowsMature ? "Yes" : "No"}</span>
              </div>

              <div className="flex justify-between">
                <span className="opacity-70">Local Only:</span>
                <span>{policy.localOnly ? "Yes" : "No"}</span>
              </div>

              <div className="flex justify-between">
                <span className="opacity-70">Allowed Providers:</span>
                <span>{policy.allowedProviders.join(", ") || "None"}</span>
              </div>

              <div className="mt-2 pt-2 border-t">
                <div className="text-xs opacity-70 font-medium">Restrictions:</div>
                <ul className="text-xs opacity-60 mt-1 list-disc list-inside">
                  {policy.restrictions.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
TSXEOF

# ----------------------------
# frontend/src/ui/studio/tabs/TimelineTab.tsx
# ----------------------------
write_file "frontend/src/ui/studio/tabs/TimelineTab.tsx" <<'TSXEOF'
import React, { useState } from "react";
import { ContentRatingBadge } from "../components/ContentRatingBadge";

type Video = {
  id: string;
  contentRating: "sfw" | "mature";
};

/**
 * Timeline tab for clip/scene editing.
 * NSFW-aware generation with policy enforcement.
 */
export function TimelineTab({ video }: { video: Video | null }) {
  const [prompt, setPrompt] = useState("");
  const [provider, setProvider] = useState("ollama");
  const [result, setResult] = useState<{ ok: boolean; error?: string; flags?: string[] } | null>(null);
  const [loading, setLoading] = useState(false);

  async function checkPolicy() {
    if (!video?.id || !prompt.trim()) return;

    setLoading(true);
    setResult(null);

    try {
      const r = await fetch(`/studio/videos/${video.id}/policy/check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: prompt.trim(), provider }),
      });
      const j = await r.json();
      setResult(j);
    } catch (e: any) {
      setResult({ ok: false, error: e.message });
    } finally {
      setLoading(false);
    }
  }

  if (!video) return null;

  return (
    <div className="p-6">
      <div className="flex items-center gap-3">
        <div className="text-lg font-semibold">Timeline</div>
        <ContentRatingBadge value={video.contentRating} />
      </div>
      <div className="text-sm opacity-70 mt-1">
        Clip and scene editor with policy-enforced generation.
      </div>

      {/* Policy check demo */}
      <div className="mt-6 border rounded p-4 max-w-xl">
        <div className="font-semibold text-sm">Generation Policy Check</div>
        <div className="text-xs opacity-70 mt-1">
          Test if a prompt would be allowed by current policy.
        </div>

        <div className="mt-3 grid gap-3">
          <div>
            <label className="text-xs mb-1 block">Prompt</label>
            <textarea
              className="w-full border rounded px-2 py-1 text-sm resize-none"
              rows={3}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Describe what you want to generate..."
            />
          </div>

          <div>
            <label className="text-xs mb-1 block">Provider</label>
            <select
              className="border rounded px-2 py-1 text-sm"
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
            >
              <option value="ollama">Ollama (local)</option>
              <option value="openai">OpenAI</option>
              <option value="comfyui">ComfyUI</option>
            </select>
          </div>

          <button
            className="px-3 py-1 rounded border text-sm hover:bg-muted/30 disabled:opacity-50"
            onClick={checkPolicy}
            disabled={!prompt.trim() || loading}
          >
            {loading ? "Checking..." : "Check Policy"}
          </button>

          {result && (
            <div
              className={`p-2 rounded border text-sm ${
                result.ok
                  ? "bg-green-500/10 border-green-500/30"
                  : "bg-red-500/10 border-red-500/30"
              }`}
            >
              {result.ok ? (
                <div>✅ Allowed</div>
              ) : (
                <div>❌ Blocked: {result.error}</div>
              )}
              {result.flags && result.flags.length > 0 && (
                <div className="text-xs opacity-70 mt-1">
                  Flags: {result.flags.join(", ")}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Placeholder for actual timeline UI */}
      <div className="mt-6 border rounded p-8 text-center opacity-70">
        <div className="text-sm">Timeline editor coming soon.</div>
        <div className="text-xs mt-1">
          Clips, scenes, and NSFW-aware generation controls.
        </div>
      </div>
    </div>
  );
}
TSXEOF

# ----------------------------
# frontend/src/ui/studio/tabs/PlayerTab.tsx
# ----------------------------
write_file "frontend/src/ui/studio/tabs/PlayerTab.tsx" <<'TSXEOF'
import React from "react";
import { ContentRatingBadge } from "../components/ContentRatingBadge";

type Video = {
  id: string;
  title: string;
  contentRating: "sfw" | "mature";
};

export function PlayerTab({ video }: { video: Video | null }) {
  if (!video) return null;

  return (
    <div className="h-full flex flex-col">
      <div className="p-4 border-b flex items-center gap-3">
        <div className="font-semibold">Player</div>
        <ContentRatingBadge value={video.contentRating} />
        {video.contentRating === "mature" && (
          <span className="text-xs opacity-70">
            (thumbnails may be blurred for enterprise settings)
          </span>
        )}
      </div>

      <div className="flex-1 flex items-center justify-center bg-black/90">
        <div className="text-white/70 text-center">
          <div className="text-lg">▶</div>
          <div className="text-sm mt-2">{video.title}</div>
          <div className="text-xs mt-1 opacity-50">
            Video player coming soon
          </div>
        </div>
      </div>
    </div>
  );
}
TSXEOF

# ----------------------------
# frontend/src/ui/studio/tabs/ExportTab.tsx
# ----------------------------
write_file "frontend/src/ui/studio/tabs/ExportTab.tsx" <<'TSXEOF'
import React, { useEffect, useState } from "react";

type Video = {
  id: string;
  contentRating: "sfw" | "mature";
};

type ExportOption = {
  kind: string;
  label: string;
  available: boolean;
};

export function ExportTab({ video }: { video: Video | null }) {
  const [exports, setExports] = useState<ExportOption[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!video?.id) return;

    fetch(`/studio/videos/${video.id}/exports`)
      .then((r) => r.json())
      .then((j) => setExports(j.exports || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [video?.id]);

  if (!video) return null;

  return (
    <div className="p-6">
      <div className="text-lg font-semibold">Export</div>
      <div className="text-sm opacity-70 mt-1">
        Download your project in various formats.
      </div>

      {video.contentRating === "mature" && (
        <div className="mt-4 p-3 border rounded bg-yellow-500/10 border-yellow-500/30 text-sm">
          ⚠️ <strong>Mature content restrictions:</strong>
          <ul className="list-disc list-inside mt-1 text-xs opacity-80">
            <li>Public sharing may be disabled</li>
            <li>YouTube preset may require compliance confirmation</li>
            <li>No exports to restricted platforms</li>
          </ul>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 mt-6 max-w-xl">
        {loading ? (
          <div className="col-span-2 text-sm opacity-70">Loading exports...</div>
        ) : (
          exports.map((exp) => (
            <div
              key={exp.kind}
              className={`border rounded p-4 ${
                exp.available ? "hover:bg-muted/30 cursor-pointer" : "opacity-50"
              }`}
            >
              <div className="font-semibold text-sm">{exp.label}</div>
              <div className="text-xs opacity-70 mt-1">
                {exp.available ? "Available" : "Not available for this preset"}
              </div>
              {exp.available && (
                <button className="mt-3 text-xs px-3 py-1 rounded border">
                  Export
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
TSXEOF

# ----------------------------
# frontend/src/ui/studio/tabs/ActivityTab.tsx
# ----------------------------
write_file "frontend/src/ui/studio/tabs/ActivityTab.tsx" <<'TSXEOF'
import React, { useEffect, useState } from "react";

type Video = {
  id: string;
};

type AuditEvent = {
  eventId: string;
  type: string;
  actor: string;
  timestamp: number;
  payload: Record<string, any>;
};

export function ActivityTab({ video }: { video: Video | null }) {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    if (!video?.id) return;

    setLoading(true);
    const params = new URLSearchParams();
    if (filter) params.set("event_type", filter);

    fetch(`/studio/videos/${video.id}/audit?${params.toString()}`)
      .then((r) => r.json())
      .then((j) => setEvents(j.events || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [video?.id, filter]);

  if (!video) return null;

  return (
    <div className="p-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-lg font-semibold">Activity</div>
          <div className="text-sm opacity-70 mt-1">
            Audit log for compliance tracking.
          </div>
        </div>

        <select
          className="border rounded px-2 py-1 text-sm"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="">All events</option>
          <option value="create_video">Created</option>
          <option value="policy_check">Policy checks</option>
          <option value="export">Exports</option>
          <option value="update_content_rating">Rating changes</option>
        </select>
      </div>

      <div className="mt-6 border rounded">
        {loading ? (
          <div className="p-4 text-sm opacity-70">Loading...</div>
        ) : events.length === 0 ? (
          <div className="p-4 text-sm opacity-70">No events found.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/30">
                <th className="text-left p-2 font-medium">Type</th>
                <th className="text-left p-2 font-medium">Actor</th>
                <th className="text-left p-2 font-medium">Time</th>
                <th className="text-left p-2 font-medium">Details</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.eventId} className="border-b">
                  <td className="p-2">
                    <span
                      className={`px-2 py-0.5 rounded text-xs ${
                        e.type === "policy_check" && !e.payload.allowed
                          ? "bg-red-500/10"
                          : ""
                      }`}
                    >
                      {e.type}
                    </span>
                  </td>
                  <td className="p-2 opacity-70">{e.actor}</td>
                  <td className="p-2 opacity-70">
                    {new Date(e.timestamp * 1000).toLocaleString()}
                  </td>
                  <td className="p-2 text-xs opacity-60 max-w-xs truncate">
                    {e.payload.reason || e.payload.kind || JSON.stringify(e.payload).slice(0, 50)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
TSXEOF

# ----------------------------
# frontend/src/ui/studio/tabs/index.ts
# ----------------------------
write_file "frontend/src/ui/studio/tabs/index.ts" <<'TSEOF'
export { OverviewTab } from "./OverviewTab";
export { BibleTab } from "./BibleTab";
export { TimelineTab } from "./TimelineTab";
export { PlayerTab } from "./PlayerTab";
export { ExportTab } from "./ExportTab";
export { ActivityTab } from "./ActivityTab";
TSEOF

# ----------------------------
# frontend/src/ui/studio/index.ts
# ----------------------------
write_file "frontend/src/ui/studio/index.ts" <<'TSEOF'
/**
 * Studio module exports.
 *
 * Usage in your app router:
 *   import { StudioRoutes } from "@/ui/studio";
 *   <Route path="/studio/*" element={<StudioRoutes />} />
 */
export { StudioRoutes } from "./StudioRoutes";
export { StudioShell } from "./StudioShell";
export { StudioLibraryRail } from "./StudioLibraryRail";

export * from "./components";
export * from "./tabs";
TSEOF

echo ""
echo "=============================================="
echo "✅ Studio scaffold created successfully!"
echo "=============================================="
echo ""
echo "Files created:"
echo ""
echo "Backend (backend/app/studio/):"
echo "  - __init__.py"
echo "  - models.py"
echo "  - policy.py     (NSFW policy engine)"
echo "  - audit.py      (audit logging)"
echo "  - repo.py       (in-memory storage)"
echo "  - service.py    (business logic)"
echo "  - exporter.py   (export functionality)"
echo "  - routes.py     (FastAPI endpoints)"
echo ""
echo "Frontend (frontend/src/ui/studio/):"
echo "  - index.ts"
echo "  - StudioRoutes.tsx"
echo "  - StudioShell.tsx"
echo "  - StudioLibraryRail.tsx"
echo "  - components/"
echo "      - index.ts"
echo "      - ContentRatingBadge.tsx"
echo "      - StatusBadge.tsx"
echo "      - PlatformBadge.tsx"
echo "      - PolicyBanner.tsx"
echo "  - pages/"
echo "      - StudioHome.tsx"
echo "      - StudioNewWizard.tsx"
echo "      - StudioWorkspace.tsx"
echo "  - tabs/"
echo "      - index.ts"
echo "      - OverviewTab.tsx"
echo "      - BibleTab.tsx"
echo "      - TimelineTab.tsx"
echo "      - PlayerTab.tsx"
echo "      - ExportTab.tsx"
echo "      - ActivityTab.tsx"
echo ""
echo "=============================================="
echo "Next steps:"
echo "=============================================="
echo ""
echo "1. Mount backend router in your FastAPI app:"
echo "   from app.studio import router as studio_router"
echo "   app.include_router(studio_router)"
echo ""
echo "2. Mount frontend routes in your React router:"
echo '   import { StudioRoutes } from "@/ui/studio";'
echo '   <Route path="/studio/*" element={<StudioRoutes />} />'
echo ""
echo "3. Enable mature content (optional):"
echo "   export STUDIO_ALLOW_MATURE=1"
echo ""
echo "=============================================="
