"""
Persona Runtime Manager — resolves v3 persona profiles at runtime.

Additive module: does not modify any existing HomePilot code.
Loads cognitive, embodiment, VR, voice, and relationship profiles
from persona project data and presents a unified runtime config.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Profile dataclasses ───────────────────────────────────────────────


@dataclass
class CognitiveConfig:
    """How the persona thinks."""

    reasoning_mode: str = "direct"
    memory_strategy: str = "basic"
    initiative_level: str = "reactive"
    action_confirmation: str = "always"
    allowed_tool_categories: List[str] = field(default_factory=list)
    spatial_intelligence_enabled: bool = False
    world_state_aware: bool = False
    multi_step_planning: bool = False
    self_reflection: bool = False
    tool_chaining: bool = False
    emotional_continuity: bool = False
    workflow_graphs: List[str] = field(default_factory=list)
    content_rating: str = "sfw"
    tool_autonomy_cap: str = "none"
    relationship_boundary: str = "professional"


@dataclass
class EmbodimentConfig:
    """How the persona moves."""

    expression_style: str = "moderate"
    look_at_intensity: float = 0.7
    gesture_amplitude: str = "moderate"
    talk_style: str = "subtle_nod"
    idle_style: str = "breathing"
    default_pose: str = "standing_relaxed"
    personal_distance_m: float = 1.2
    can_sit: bool = True
    can_offer_hand: bool = False
    can_high_five: bool = False


@dataclass
class VRConfig:
    """How the persona behaves in VR/AR."""

    vrm_file: str = ""
    vrm_fallback: str = ""
    spawn_distance_m: float = 1.5
    follow_enabled: bool = True
    follow_distance_m: float = 1.5
    follow_side: str = "adaptive"
    locomotion_style: str = "walk"
    walk_speed_mps: float = 1.2
    presence_states: List[str] = field(
        default_factory=lambda: ["idle", "listening", "thinking", "speaking"]
    )
    interaction_commands: List[str] = field(
        default_factory=lambda: ["come here", "follow me", "stop"]
    )
    supports_vr: bool = True
    supports_ar: bool = False
    preferred_environment: str = "any"


@dataclass
class VoiceConfig:
    """How the persona sounds."""

    voice_id: str = ""
    voice_provider: str = "auto"
    pitch_bias: float = 0.0
    rate_bias: float = 0.0
    pause_style: str = "natural"
    warmth: float = 0.5


@dataclass
class RelationshipConfig:
    """The relational dynamic."""

    relationship_type: str = "professional"
    emotional_continuity: bool = False
    initiative_balance: str = "balanced"
    formality: str = "casual"
    humor_level: str = "light"
    empathy_depth: str = "moderate"
    allows_physical_interaction_vr: bool = False


@dataclass
class PersonaRuntimeConfig:
    """Unified runtime config for a v3 persona."""

    persona_id: str = ""
    display_name: str = ""
    role: str = ""
    schema_version: int = 2
    cognitive: CognitiveConfig = field(default_factory=CognitiveConfig)
    embodiment: EmbodimentConfig = field(default_factory=EmbodimentConfig)
    vr: VRConfig = field(default_factory=VRConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    relationship: RelationshipConfig = field(default_factory=RelationshipConfig)

    @property
    def is_v3(self) -> bool:
        return self.schema_version >= 3

    @property
    def is_orchestrated(self) -> bool:
        return self.cognitive.reasoning_mode == "orchestrated"

    @property
    def is_vr_ready(self) -> bool:
        return bool(self.vr.vrm_file)

    @property
    def has_spatial_intelligence(self) -> bool:
        return self.cognitive.spatial_intelligence_enabled


# ── Builder ───────────────────────────────────────────────────────────


def build_runtime_config(
    persona_agent: Dict[str, Any],
    manifest: Dict[str, Any],
    cognitive: Optional[Dict[str, Any]] = None,
    embodiment: Optional[Dict[str, Any]] = None,
    vr_profile: Optional[Dict[str, Any]] = None,
    voice: Optional[Dict[str, Any]] = None,
    relationship: Optional[Dict[str, Any]] = None,
) -> PersonaRuntimeConfig:
    """Build a PersonaRuntimeConfig from raw profile dicts.

    Handles missing profiles gracefully (v2 compatibility).
    """
    cog = cognitive or {}
    emb = embodiment or {}
    vrp = vr_profile or {}
    voi = voice or {}
    rel = relationship or {}

    spatial = cog.get("spatial_intelligence", {})
    safety = cog.get("safety_policy", {})
    si_traits = cog.get("superintelligence_traits", {})
    look = emb.get("look_at", {})
    gest = emb.get("gestures", {})
    posture = emb.get("posture", {})
    dist = emb.get("personal_distance", {})
    hand = emb.get("hand_interactions", {})
    vrm = vrp.get("vrm_binding", {})
    spawn = vrp.get("spawn", {})
    follow = vrp.get("following", {})
    nav = vrp.get("navigation", {})
    xr = vrp.get("xr_preferences", {})

    return PersonaRuntimeConfig(
        persona_id=persona_agent.get("id", ""),
        display_name=persona_agent.get("label", ""),
        role=persona_agent.get("role", ""),
        schema_version=manifest.get("schema_version", 2),
        cognitive=CognitiveConfig(
            reasoning_mode=cog.get("reasoning_mode", "direct"),
            memory_strategy=cog.get("memory_strategy", "basic"),
            initiative_level=cog.get("initiative_level", "reactive"),
            action_confirmation=cog.get("action_confirmation", "always"),
            allowed_tool_categories=cog.get("allowed_tool_categories", []),
            spatial_intelligence_enabled=spatial.get("enabled", False),
            world_state_aware=spatial.get("world_state_aware", False),
            multi_step_planning=si_traits.get("multi_step_planning", False),
            self_reflection=si_traits.get("self_reflection", False),
            tool_chaining=si_traits.get("tool_chaining", False),
            emotional_continuity=si_traits.get("emotional_continuity", False),
            workflow_graphs=si_traits.get("workflow_graphs", []),
            content_rating=safety.get("content_rating", "sfw"),
            tool_autonomy_cap=safety.get("tool_autonomy_cap", "none"),
            relationship_boundary=safety.get("relationship_boundary", "professional"),
        ),
        embodiment=EmbodimentConfig(
            expression_style=emb.get("expression_style", "moderate"),
            look_at_intensity=look.get("intensity", 0.7),
            gesture_amplitude=gest.get("amplitude", "moderate"),
            talk_style=gest.get("talk_style", "subtle_nod"),
            idle_style=gest.get("idle_style", "breathing"),
            default_pose=posture.get("default_pose", "standing_relaxed"),
            personal_distance_m=dist.get("default_m", 1.2),
            can_sit=posture.get("can_sit", True),
            can_offer_hand=hand.get("can_offer_hand", False),
            can_high_five=hand.get("can_high_five", False),
        ),
        vr=VRConfig(
            vrm_file=vrm.get("vrm_file", ""),
            vrm_fallback=vrm.get("vrm_fallback", ""),
            spawn_distance_m=spawn.get("distance_m", 1.5),
            follow_enabled=follow.get("enabled", True),
            follow_distance_m=follow.get("follow_distance_m", 1.5),
            follow_side=follow.get("follow_side", "adaptive"),
            locomotion_style=vrp.get("locomotion_style", "walk"),
            walk_speed_mps=nav.get("walk_speed_mps", 1.2),
            presence_states=vrp.get("presence_states", [
                "idle", "listening", "thinking", "speaking",
            ]),
            interaction_commands=vrp.get("interaction_commands", [
                "come here", "follow me", "stop",
            ]),
            supports_vr=xr.get("supports_vr", True),
            supports_ar=xr.get("supports_ar", False),
            preferred_environment=xr.get("preferred_environment", "any"),
        ),
        voice=VoiceConfig(
            voice_id=voi.get("voice_id", ""),
            voice_provider=voi.get("voice_provider", "auto"),
            pitch_bias=voi.get("pitch_bias", 0.0),
            rate_bias=voi.get("rate_bias", 0.0),
            pause_style=voi.get("pause_style", "natural"),
            warmth=voi.get("warmth", 0.5),
        ),
        relationship=RelationshipConfig(
            relationship_type=rel.get("relationship_type", "professional"),
            emotional_continuity=rel.get("emotional_continuity", False),
            initiative_balance=rel.get("initiative_balance", "balanced"),
            formality=rel.get("formality", "casual"),
            humor_level=rel.get("humor_level", "light"),
            empathy_depth=rel.get("empathy_depth", "moderate"),
            allows_physical_interaction_vr=rel.get("boundary_rules", {}).get(
                "allows_physical_interaction_vr", False
            ),
        ),
    )


# ── Profile loader from persona directory ─────────────────────────────


def load_v3_profiles(persona_dir: Path) -> Dict[str, Any]:
    """Load all v3 profile files from a persona blueprint directory.

    Returns a dict with keys: persona_agent, manifest, cognitive,
    embodiment, vr_profile, voice, relationship.
    Missing files return None for that key.
    """
    blueprint = persona_dir / "blueprint"
    result: Dict[str, Any] = {}

    file_map = {
        "persona_agent": blueprint / "persona_agent.json",
        "manifest": persona_dir / "manifest.json",
        "cognitive": blueprint / "cognitive_profile.json",
        "embodiment": blueprint / "embodiment_profile.json",
        "vr_profile": blueprint / "vr_profile.json",
        "voice": blueprint / "voice_profile.json",
        "relationship": blueprint / "relationship_model.json",
    }

    for key, path in file_map.items():
        if path.is_file():
            try:
                with open(path) as f:
                    result[key] = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load %s from %s: %s", key, path, exc)
                result[key] = None
        else:
            result[key] = None

    return result


def resolve_persona(persona_dir: Path) -> PersonaRuntimeConfig:
    """Load and resolve a full PersonaRuntimeConfig from a persona directory."""
    profiles = load_v3_profiles(persona_dir)
    if not profiles.get("persona_agent") or not profiles.get("manifest"):
        raise FileNotFoundError(
            f"Missing persona_agent.json or manifest.json in {persona_dir}"
        )
    return build_runtime_config(**profiles)
