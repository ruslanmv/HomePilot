"""
Studio Library - Style Kits and Templates

Provides reusable design systems and project templates for:
- YouTube Creators (videos, shorts)
- Professionals (presentations, slides)
- Enterprise (training, documentation)
"""
from __future__ import annotations

from typing import List, Optional

from .models import CanvasSpec, ProjectType, StyleKit, TemplateDefinition


def normalize_project_type(pt: str) -> ProjectType:
    """Normalize various project type inputs to canonical values."""
    if pt in ("youtube_video", "youtube_short", "slides"):
        return pt  # type: ignore[return-value]
    aliases = {
        "video": "youtube_video",
        "short": "youtube_short",
        "shorts": "youtube_short",
        "ppt": "slides",
        "pptx": "slides",
        "presentation": "slides",
    }
    return aliases.get(pt, "youtube_video")  # type: ignore[return-value]


def default_canvas(pt: ProjectType) -> CanvasSpec:
    """Get default canvas specification for a project type."""
    if pt == "youtube_short":
        return CanvasSpec(width=1080, height=1920, fps=30, safe_margin_pct=0.06)
    # youtube_video & slides default to 16:9
    return CanvasSpec(width=1920, height=1080, fps=30, safe_margin_pct=0.05)


# ============================================================================
# Style Kits - Reusable Design Systems
# ============================================================================

STYLE_KITS: List[StyleKit] = [
    StyleKit(
        id="sk_creator_dark",
        name="Creator Dark",
        description="YouTube-friendly dark theme with punchy accents.",
        palette={
            "primary": "#F9FAFB",
            "secondary": "#EF4444",
            "bg": "#0B1220",
            "muted": "#9CA3AF",
        },
        fonts={"heading": "Inter", "body": "Inter"},
        spacing={"base": 8, "xl": 24},
        motion={"transition": "slide", "duration": 0.35},
    ),
    StyleKit(
        id="sk_modern_light",
        name="Modern Light",
        description="Clean, high-contrast, classroom-friendly.",
        palette={
            "primary": "#111827",
            "secondary": "#2563EB",
            "bg": "#FFFFFF",
            "muted": "#6B7280",
        },
        fonts={"heading": "Inter", "body": "Inter"},
        spacing={"base": 8, "xl": 24},
        motion={"transition": "fade", "duration": 0.40},
    ),
    StyleKit(
        id="sk_vibrant",
        name="Vibrant",
        description="Bold colors for attention-grabbing content.",
        palette={
            "primary": "#FFFFFF",
            "secondary": "#F59E0B",
            "bg": "#7C3AED",
            "muted": "#DDD6FE",
        },
        fonts={"heading": "Inter", "body": "Inter"},
        spacing={"base": 8, "xl": 24},
        motion={"transition": "zoom", "duration": 0.30},
    ),
    StyleKit(
        id="sk_corporate",
        name="Corporate",
        description="Professional and trustworthy for enterprise use.",
        palette={
            "primary": "#1E293B",
            "secondary": "#0EA5E9",
            "bg": "#F8FAFC",
            "muted": "#64748B",
        },
        fonts={"heading": "Inter", "body": "Inter"},
        spacing={"base": 8, "xl": 24},
        motion={"transition": "fade", "duration": 0.45},
    ),
]


# ============================================================================
# Templates - Project Scaffolds
# ============================================================================

TEMPLATES: List[TemplateDefinition] = [
    # YouTube Video Templates
    TemplateDefinition(
        id="tpl_youtube_explainer",
        name="YouTube Explainer",
        description="Hook → 3 points → recap → CTA",
        projectType="youtube_video",
        styleKitId="sk_creator_dark",
        frames=[
            {"kind": "scene", "title": "Hook", "layers": [{"type": "title"}, {"type": "subtitle"}]},
            {"kind": "scene", "title": "Point 1", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "scene", "title": "Point 2", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "scene", "title": "Point 3", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "scene", "title": "Recap", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "scene", "title": "CTA", "layers": [{"type": "title"}, {"type": "subtitle"}]},
        ],
    ),
    TemplateDefinition(
        id="tpl_youtube_tutorial",
        name="YouTube Tutorial",
        description="Intro → Steps → Demo → Summary",
        projectType="youtube_video",
        styleKitId="sk_modern_light",
        frames=[
            {"kind": "scene", "title": "Intro", "layers": [{"type": "title"}, {"type": "subtitle"}]},
            {"kind": "scene", "title": "Step 1", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "scene", "title": "Step 2", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "scene", "title": "Step 3", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "scene", "title": "Demo", "layers": [{"type": "title"}, {"type": "media"}]},
            {"kind": "scene", "title": "Summary", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "scene", "title": "Subscribe", "layers": [{"type": "title"}, {"type": "cta"}]},
        ],
    ),
    # YouTube Shorts Templates
    TemplateDefinition(
        id="tpl_shorts_quick_tip",
        name="Shorts Quick Tip",
        description="1 idea, fast pacing, captions-first.",
        projectType="youtube_short",
        styleKitId="sk_creator_dark",
        frames=[
            {"kind": "scene", "title": "Hook", "layers": [{"type": "big_text"}]},
            {"kind": "scene", "title": "Tip", "layers": [{"type": "big_text"}, {"type": "caption"}]},
            {"kind": "scene", "title": "CTA", "layers": [{"type": "big_text"}]},
        ],
    ),
    TemplateDefinition(
        id="tpl_shorts_fact",
        name="Shorts Did You Know",
        description="Surprising fact with visual impact.",
        projectType="youtube_short",
        styleKitId="sk_vibrant",
        frames=[
            {"kind": "scene", "title": "Question", "layers": [{"type": "big_text"}]},
            {"kind": "scene", "title": "Reveal", "layers": [{"type": "big_text"}, {"type": "media"}]},
            {"kind": "scene", "title": "Follow", "layers": [{"type": "big_text"}]},
        ],
    ),
    # Slides/Presentation Templates
    TemplateDefinition(
        id="tpl_slides_lesson",
        name="Lesson Slides",
        description="Title → agenda → 3 content → summary",
        projectType="slides",
        styleKitId="sk_modern_light",
        frames=[
            {"kind": "slide", "title": "Title", "layers": [{"type": "title"}, {"type": "subtitle"}]},
            {"kind": "slide", "title": "Agenda", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "slide", "title": "Concept 1", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "slide", "title": "Concept 2", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "slide", "title": "Concept 3", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "slide", "title": "Summary", "layers": [{"type": "title"}, {"type": "bullets"}]},
        ],
    ),
    TemplateDefinition(
        id="tpl_slides_pitch",
        name="Pitch Deck",
        description="Problem → Solution → Market → Team → Ask",
        projectType="slides",
        styleKitId="sk_corporate",
        frames=[
            {"kind": "slide", "title": "Title", "layers": [{"type": "title"}, {"type": "subtitle"}]},
            {"kind": "slide", "title": "Problem", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "slide", "title": "Solution", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "slide", "title": "Market", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "slide", "title": "Team", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "slide", "title": "The Ask", "layers": [{"type": "title"}, {"type": "cta"}]},
        ],
    ),
    TemplateDefinition(
        id="tpl_slides_training",
        name="Training Module",
        description="Overview → Objectives → Content → Quiz → Summary",
        projectType="slides",
        styleKitId="sk_corporate",
        frames=[
            {"kind": "slide", "title": "Overview", "layers": [{"type": "title"}, {"type": "subtitle"}]},
            {"kind": "slide", "title": "Objectives", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "slide", "title": "Topic 1", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "slide", "title": "Topic 2", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "slide", "title": "Topic 3", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "slide", "title": "Key Takeaways", "layers": [{"type": "title"}, {"type": "bullets"}]},
            {"kind": "slide", "title": "Questions", "layers": [{"type": "title"}]},
        ],
    ),
]


def list_style_kits() -> List[StyleKit]:
    """Get all available style kits."""
    return list(STYLE_KITS)


def get_style_kit(kit_id: str) -> Optional[StyleKit]:
    """Get a style kit by ID."""
    for kit in STYLE_KITS:
        if kit.id == kit_id:
            return kit
    return None


def list_templates(project_type: Optional[str] = None) -> List[TemplateDefinition]:
    """Get templates, optionally filtered by project type."""
    if not project_type:
        return list(TEMPLATES)
    pt = normalize_project_type(project_type)
    return [t for t in TEMPLATES if t.projectType == pt]


def get_template(template_id: str) -> Optional[TemplateDefinition]:
    """Get a template by ID."""
    for tpl in TEMPLATES:
        if tpl.id == template_id:
            return tpl
    return None
