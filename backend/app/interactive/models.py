"""
Pydantic data contracts for the interactive service.

One model per concept — read-side rows returned by the repo and
write-side create/update payloads used by the router. Field names
map 1:1 to the column names in ``store.py`` so downstream
conversions stay mechanical.

All models allow extra fields on read (``model_config`` below) so
future batches can add columns without breaking existing clients.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# Shared config — be permissive on input/output so adding fields
# later never 422s a caller.
_PERMISSIVE = ConfigDict(extra="allow", populate_by_name=True)


# ─────────────────────────────────────────────────────────────────
# Enumerations (stable string literals)
# ─────────────────────────────────────────────────────────────────

ExperienceMode = Literal[
    "sfw_general",
    "sfw_education",
    "language_learning",
    "enterprise_training",
    "social_romantic",
    "mature_gated",
]

ExperienceStatus = Literal[
    "draft", "planning", "building", "ready", "published", "archived",
]

NodeKind = Literal["scene", "decision", "merge", "ending", "assessment", "remediation"]

EdgeTriggerKind = Literal["choice", "hotspot", "timer", "auto", "fallback", "intent"]

TurnRole = Literal["user", "assistant", "system"]

EventKind = Literal[
    "start", "enter_node", "choose", "hotspot", "drop_off",
    "complete", "policy_block", "error",
]

ProgressionScheme = Literal[
    "xp_level", "mastery", "cefr", "affinity_tier", "certification",
]

PublishChannel = Literal["web_embed", "lms", "kiosk", "api"]


# ─────────────────────────────────────────────────────────────────
# Experience
# ─────────────────────────────────────────────────────────────────

class ExperienceCreate(BaseModel):
    model_config = _PERMISSIVE
    title: str
    description: str = ""
    objective: str = ""
    experience_mode: ExperienceMode = "sfw_general"
    policy_profile_id: str = "sfw_general"
    audience_profile: Dict[str, Any] = Field(default_factory=dict)
    studio_video_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class ExperienceUpdate(BaseModel):
    model_config = _PERMISSIVE
    title: Optional[str] = None
    description: Optional[str] = None
    objective: Optional[str] = None
    experience_mode: Optional[ExperienceMode] = None
    policy_profile_id: Optional[str] = None
    audience_profile: Optional[Dict[str, Any]] = None
    status: Optional[ExperienceStatus] = None
    tags: Optional[List[str]] = None


class Experience(BaseModel):
    model_config = _PERMISSIVE
    id: str
    user_id: str
    studio_video_id: str = ""
    title: str
    description: str = ""
    objective: str = ""
    experience_mode: ExperienceMode = "sfw_general"
    policy_profile_id: str = "sfw_general"
    audience_profile: Dict[str, Any] = Field(default_factory=dict)
    branch_count: int = 0
    max_depth: int = 0
    status: ExperienceStatus = "draft"
    tags: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ─────────────────────────────────────────────────────────────────
# Graph — nodes + edges
# ─────────────────────────────────────────────────────────────────

class NodeCreate(BaseModel):
    model_config = _PERMISSIVE
    kind: NodeKind = "scene"
    title: str = ""
    narration: str = ""
    image_prompt: str = ""
    video_prompt: str = ""
    duration_sec: int = 5
    storyboard: Dict[str, Any] = Field(default_factory=dict)
    interaction_layout: Dict[str, Any] = Field(default_factory=dict)
    asset_ids: List[str] = Field(default_factory=list)


class NodeUpdate(BaseModel):
    model_config = _PERMISSIVE
    kind: Optional[NodeKind] = None
    title: Optional[str] = None
    narration: Optional[str] = None
    image_prompt: Optional[str] = None
    video_prompt: Optional[str] = None
    duration_sec: Optional[int] = None
    storyboard: Optional[Dict[str, Any]] = None
    interaction_layout: Optional[Dict[str, Any]] = None
    asset_ids: Optional[List[str]] = None


class Node(BaseModel):
    model_config = _PERMISSIVE
    id: str
    experience_id: str
    kind: NodeKind
    title: str = ""
    narration: str = ""
    image_prompt: str = ""
    video_prompt: str = ""
    duration_sec: int = 5
    storyboard: Dict[str, Any] = Field(default_factory=dict)
    interaction_layout: Dict[str, Any] = Field(default_factory=dict)
    asset_ids: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class EdgeCreate(BaseModel):
    model_config = _PERMISSIVE
    from_node_id: str
    to_node_id: str
    trigger_kind: EdgeTriggerKind
    trigger_payload: Dict[str, Any] = Field(default_factory=dict)
    ordinal: int = 0


class Edge(BaseModel):
    model_config = _PERMISSIVE
    id: str
    experience_id: str
    from_node_id: str
    to_node_id: str
    trigger_kind: EdgeTriggerKind
    trigger_payload: Dict[str, Any] = Field(default_factory=dict)
    ordinal: int = 0
    created_at: Optional[str] = None


class NodeVariant(BaseModel):
    model_config = _PERMISSIVE
    id: str
    node_id: str
    language: str
    narration: str = ""
    subtitles: str = ""
    audio_asset_id: str = ""
    video_asset_id: str = ""


# ─────────────────────────────────────────────────────────────────
# Runtime — sessions / turns / events
# ─────────────────────────────────────────────────────────────────

class Session(BaseModel):
    model_config = _PERMISSIVE
    id: str
    experience_id: str
    viewer_ref: str = ""
    current_node_id: str = ""
    language: str = "en"
    personalization: Dict[str, Any] = Field(default_factory=dict)
    consent_version: str = ""
    started_at: Optional[str] = None
    last_event_at: Optional[str] = None
    completed_at: Optional[str] = None


class SessionTurn(BaseModel):
    model_config = _PERMISSIVE
    id: str
    session_id: str
    turn_role: TurnRole
    text: str
    action_id: str = ""
    node_id: str = ""
    created_at: Optional[str] = None


class SessionEvent(BaseModel):
    model_config = _PERMISSIVE
    id: str
    session_id: str
    ts: Optional[str] = None
    event_kind: EventKind
    node_id: str = ""
    edge_id: str = ""
    action_id: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────
# Character + assets
# ─────────────────────────────────────────────────────────────────

class CharacterState(BaseModel):
    model_config = _PERMISSIVE
    id: str
    session_id: str
    persona_id: str = ""
    mood: str = "neutral"
    affinity_score: float = 0.5
    outfit_state: Dict[str, Any] = Field(default_factory=dict)
    recent_flags: List[str] = Field(default_factory=list)
    language: str = "en"
    updated_at: Optional[str] = None


class CharacterAsset(BaseModel):
    model_config = _PERMISSIVE
    id: str
    persona_id: str
    asset_id: str
    kind: str
    mood_tags: List[str] = Field(default_factory=list)
    action_tags: List[str] = Field(default_factory=list)
    language: str = ""
    outfit_tags: List[str] = Field(default_factory=list)
    duration_sec: float = 0.0
    intensity: float = 0.5
    created_at: Optional[str] = None


# ─────────────────────────────────────────────────────────────────
# Actions + progression
# ─────────────────────────────────────────────────────────────────

class ActionCreate(BaseModel):
    model_config = _PERMISSIVE
    label: str
    intent_code: str = ""
    required_level: int = 1
    required_scheme: str = "xp_level"
    required_metric_key: str = "level"
    policy_scope: List[str] = Field(default_factory=list)
    cooldown_sec: int = 0
    mood_delta: Dict[str, Any] = Field(default_factory=dict)
    xp_award: int = 0
    max_uses_per_session: int = 0
    repeat_penalty: float = 0.0
    requires_consent: str = ""
    applicable_modes: List[str] = Field(default_factory=list)
    ordinal: int = 0


class Action(BaseModel):
    model_config = _PERMISSIVE
    id: str
    experience_id: str
    label: str
    intent_code: str = ""
    required_level: int = 1
    required_scheme: str = "xp_level"
    required_metric_key: str = "level"
    policy_scope: List[str] = Field(default_factory=list)
    cooldown_sec: int = 0
    mood_delta: Dict[str, Any] = Field(default_factory=dict)
    xp_award: int = 0
    max_uses_per_session: int = 0
    repeat_penalty: float = 0.0
    requires_consent: str = ""
    applicable_modes: List[str] = Field(default_factory=list)
    ordinal: int = 0
    created_at: Optional[str] = None


class ProgressMetric(BaseModel):
    model_config = _PERMISSIVE
    id: str
    session_id: str
    scheme: ProgressionScheme
    metric_key: str
    metric_value: float
    updated_at: Optional[str] = None


# ─────────────────────────────────────────────────────────────────
# Personalization + intent map
# ─────────────────────────────────────────────────────────────────

class PersonalizationRule(BaseModel):
    model_config = _PERMISSIVE
    id: str
    experience_id: str
    name: str
    condition: Dict[str, Any] = Field(default_factory=dict)
    action: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 100
    enabled: bool = True
    created_at: Optional[str] = None


class IntentMapEntry(BaseModel):
    model_config = _PERMISSIVE
    id: str
    experience_id: str
    intent_code: str
    action_id: str = ""
    fallback_node_id: str = ""
    priority: int = 100
    applicable_modes: List[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Publishing + QA
# ─────────────────────────────────────────────────────────────────

class Publication(BaseModel):
    model_config = _PERMISSIVE
    id: str
    experience_id: str
    channel: PublishChannel
    manifest_url: str = ""
    version: int = 1
    metadata: Dict[str, Any] = Field(default_factory=dict)
    published_at: Optional[str] = None


class QAReport(BaseModel):
    model_config = _PERMISSIVE
    id: str
    experience_id: str
    kind: str  # 'walk' | 'lint' | 'content_check'
    summary: Dict[str, Any] = Field(default_factory=dict)
    issues: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: Optional[str] = None
