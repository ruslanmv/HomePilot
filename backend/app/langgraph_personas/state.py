"""
Persona Agent State — shared state flowing through the LangGraph pipeline.

Follows AAA-game ECS (Entity-Component-System) patterns: state is a pure
data object that nodes read/write without side-effects on each other.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class WorldSnapshot(TypedDict, total=False):
    """Spatial context from the VR client."""

    user_position: Dict[str, float]
    user_head_position: Dict[str, float]
    user_head_rotation_y_deg: float
    user_left_hand: Optional[Dict[str, float]]
    user_right_hand: Optional[Dict[str, float]]
    user_velocity_mps: float
    avatar_position: Dict[str, float]
    avatar_state: str
    avatar_distance_m: Optional[float]
    anchors: List[Dict[str, Any]]


class ToolResult(TypedDict, total=False):
    """Result from a single tool invocation."""

    tool: str
    args: Dict[str, Any]
    output: str
    media: Optional[Dict[str, Any]]


class MotionPlanDict(TypedDict, total=False):
    """Serializable motion plan for the VR client."""

    persona_id: str
    commands: List[Dict[str, Any]]
    interruptible: bool
    priority: str


class PersonaAgentState(TypedDict, total=False):
    """
    The unified state object that flows through every LangGraph node.

    Design principles (AAA game industry standard):
    - Immutable reads: nodes receive a snapshot, emit a partial update
    - No hidden state: everything the agent needs is in this dict
    - Serializable: every value is JSON-safe for checkpointing
    """

    # ── Input ────────────────────────────────────────────────────────
    user_message: str
    conversation_id: str
    project_id: str
    conversation_history: List[Dict[str, str]]

    # ── Persona identity ─────────────────────────────────────────────
    persona_id: str
    display_name: str
    reasoning_mode: str          # "direct" | "guided" | "orchestrated"
    system_prompt: str

    # ── Cognitive config ─────────────────────────────────────────────
    allowed_tool_categories: List[str]
    multi_step_planning: bool
    tool_chaining: bool
    self_reflection: bool
    workflow_graphs: List[str]
    max_tool_calls: int

    # ── Embodiment config ────────────────────────────────────────────
    expression_style: str
    gesture_amplitude: str
    personal_distance_m: float
    can_sit: bool
    can_offer_hand: bool
    can_high_five: bool

    # ── Spatial context (from world-state service) ───────────────────
    world_snapshot: WorldSnapshot

    # ── LLM settings ─────────────────────────────────────────────────
    llm_provider: str
    llm_base_url: str
    llm_model: str
    temperature: float
    max_tokens: int

    # ── Pipeline outputs (written by nodes) ──────────────────────────
    perception_summary: str       # perceive node output
    thinking_trace: str           # think node output (internal CoT)
    decision: str                 # decide node output: "respond" | "act" | "embody" | "act_and_embody"
    tool_results: List[ToolResult]
    motion_plan: Optional[MotionPlanDict]
    avatar_emotion: str           # emotion directive for VR client
    avatar_state: str             # "thinking" | "speaking" | "idle"
    response_text: str            # final text response
    response_media: Optional[Dict[str, Any]]

    # ── Control flow ─────────────────────────────────────────────────
    tool_calls_used: int
    error: str
    is_complete: bool
