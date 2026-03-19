"""
Unit tests for v3 Superintelligent Personas — schema, runtime, embodiment, world state.

Lightweight, CI-compatible (no network, no GPU, no external services).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── Paths ────────────────────────────────────────────────────────────

BUNDLES_DIR = PROJECT_ROOT / "community" / "shared" / "bundles"
SCHEMA_DIR = PROJECT_ROOT / "community" / "shared" / "_schema" / "v3"

PERSONA_IDS = [
    "scarlett_secretary",
    "milo_friend",
    "nova_collaborator",
    "luna_girlfriend",
    "velvet_companion",
]

V3_BLUEPRINT_FILES = [
    "cognitive_profile.json",
    "embodiment_profile.json",
    "vr_profile.json",
    "voice_profile.json",
    "relationship_model.json",
]


# ── Schema tests ─────────────────────────────────────────────────────


class TestV3SchemaFiles:
    """Verify all v3 JSON schema files exist and are valid JSON."""

    EXPECTED_SCHEMAS = [
        "cognitive_profile.schema.json",
        "embodiment_profile.schema.json",
        "vr_profile.schema.json",
        "voice_profile.schema.json",
        "relationship_model.schema.json",
        "workflow.schema.json",
    ]

    @pytest.mark.parametrize("schema_file", EXPECTED_SCHEMAS)
    def test_schema_file_exists(self, schema_file: str) -> None:
        path = SCHEMA_DIR / schema_file
        assert path.is_file(), f"Missing schema: {path}"

    @pytest.mark.parametrize("schema_file", EXPECTED_SCHEMAS)
    def test_schema_is_valid_json(self, schema_file: str) -> None:
        path = SCHEMA_DIR / schema_file
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "$schema" in data or "$id" in data


# ── Persona bundle structure tests ───────────────────────────────────


class TestPersonaBundleStructure:
    """Verify each of the 5 persona bundles has a complete directory tree."""

    @pytest.mark.parametrize("pid", PERSONA_IDS)
    def test_bundle_dir_exists(self, pid: str) -> None:
        assert (BUNDLES_DIR / pid).is_dir()

    @pytest.mark.parametrize("pid", PERSONA_IDS)
    def test_bundle_manifest_exists(self, pid: str) -> None:
        path = BUNDLES_DIR / pid / "bundle_manifest.json"
        assert path.is_file()

    @pytest.mark.parametrize("pid", PERSONA_IDS)
    def test_persona_manifest_exists(self, pid: str) -> None:
        path = BUNDLES_DIR / pid / "persona" / "manifest.json"
        assert path.is_file()

    @pytest.mark.parametrize("pid", PERSONA_IDS)
    def test_persona_agent_exists(self, pid: str) -> None:
        path = BUNDLES_DIR / pid / "persona" / "blueprint" / "persona_agent.json"
        assert path.is_file()

    @pytest.mark.parametrize("pid", PERSONA_IDS)
    def test_v3_blueprint_files_exist(self, pid: str) -> None:
        bp = BUNDLES_DIR / pid / "persona" / "blueprint"
        for fname in V3_BLUEPRINT_FILES:
            assert (bp / fname).is_file(), f"Missing: {bp / fname}"

    @pytest.mark.parametrize("pid", PERSONA_IDS)
    def test_card_json_exists(self, pid: str) -> None:
        path = BUNDLES_DIR / pid / "persona" / "preview" / "card.json"
        assert path.is_file()


# ── Persona manifest content tests ───────────────────────────────────


class TestPersonaManifestContent:
    """Verify manifest.json content is correct for v3."""

    @pytest.mark.parametrize("pid", PERSONA_IDS)
    def test_manifest_schema_version_3(self, pid: str) -> None:
        path = BUNDLES_DIR / pid / "persona" / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == 3

    @pytest.mark.parametrize("pid", PERSONA_IDS)
    def test_manifest_has_v3_flags(self, pid: str) -> None:
        path = BUNDLES_DIR / pid / "persona" / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        contents = data.get("contents", {})
        assert contents.get("has_cognitive_profile") is True
        assert contents.get("has_embodiment_profile") is True
        assert contents.get("has_vr_profile") is True
        assert contents.get("has_voice_profile") is True
        assert contents.get("has_relationship_model") is True


# ── Bundle manifest content tests ────────────────────────────────────


class TestBundleManifestContent:
    """Verify bundle_manifest.json content."""

    @pytest.mark.parametrize("pid", PERSONA_IDS)
    def test_bundle_id_matches_directory(self, pid: str) -> None:
        path = BUNDLES_DIR / pid / "bundle_manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["bundle_id"] == pid

    @pytest.mark.parametrize("pid", PERSONA_IDS)
    def test_schema_version_3_compat(self, pid: str) -> None:
        path = BUNDLES_DIR / pid / "bundle_manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["compatibility"]["hpersona_schema_version"] == 3


# ── Cognitive profile tests ──────────────────────────────────────────


class TestCognitiveProfiles:
    """Verify cognitive profiles have correct reasoning modes."""

    EXPECTED_MODES = {
        "scarlett_secretary": "orchestrated",
        "milo_friend": "guided",
        "nova_collaborator": "orchestrated",
        "luna_girlfriend": "guided",
        "velvet_companion": "guided",
    }

    @pytest.mark.parametrize("pid", PERSONA_IDS)
    def test_reasoning_mode(self, pid: str) -> None:
        path = BUNDLES_DIR / pid / "persona" / "blueprint" / "cognitive_profile.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["reasoning_mode"] == self.EXPECTED_MODES[pid]

    @pytest.mark.parametrize("pid", PERSONA_IDS)
    def test_spatial_intelligence_enabled(self, pid: str) -> None:
        path = BUNDLES_DIR / pid / "persona" / "blueprint" / "cognitive_profile.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["spatial_intelligence"]["enabled"] is True

    @pytest.mark.parametrize("pid", PERSONA_IDS)
    def test_has_safety_policy(self, pid: str) -> None:
        path = BUNDLES_DIR / pid / "persona" / "blueprint" / "cognitive_profile.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "safety_policy" in data
        assert "content_rating" in data["safety_policy"]


# ── VR profile tests ─────────────────────────────────────────────────


class TestVRProfiles:
    """Verify VR profiles have required fields."""

    @pytest.mark.parametrize("pid", PERSONA_IDS)
    def test_has_vrm_binding(self, pid: str) -> None:
        path = BUNDLES_DIR / pid / "persona" / "blueprint" / "vr_profile.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "vrm_binding" in data
        assert "vrm_file" in data["vrm_binding"]

    @pytest.mark.parametrize("pid", PERSONA_IDS)
    def test_has_spawn_config(self, pid: str) -> None:
        path = BUNDLES_DIR / pid / "persona" / "blueprint" / "vr_profile.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "spawn" in data
        assert "distance_m" in data["spawn"]

    @pytest.mark.parametrize("pid", PERSONA_IDS)
    def test_has_presence_states(self, pid: str) -> None:
        path = BUNDLES_DIR / pid / "persona" / "blueprint" / "vr_profile.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        states = data.get("presence_states", [])
        assert len(states) >= 4
        assert "idle" in states
        assert "speaking" in states


# ── PersonaRuntime manager tests ─────────────────────────────────────


class TestPersonaRuntimeManager:
    """Test the persona_runtime.manager module."""

    def test_import(self) -> None:
        from backend.app.persona_runtime.manager import (
            PersonaRuntimeConfig,
            build_runtime_config,
            load_v3_profiles,
            resolve_persona,
        )
        assert PersonaRuntimeConfig is not None
        assert callable(build_runtime_config)
        assert callable(load_v3_profiles)
        assert callable(resolve_persona)

    @pytest.mark.parametrize("pid", PERSONA_IDS)
    def test_resolve_persona(self, pid: str) -> None:
        from backend.app.persona_runtime.manager import resolve_persona

        persona_dir = BUNDLES_DIR / pid / "persona"
        runtime = resolve_persona(persona_dir)
        assert runtime.persona_id == pid
        assert runtime.schema_version == 3
        assert runtime.is_v3 is True
        assert runtime.is_vr_ready is True
        assert runtime.has_spatial_intelligence is True

    @pytest.mark.parametrize("pid", PERSONA_IDS)
    def test_load_v3_profiles(self, pid: str) -> None:
        from backend.app.persona_runtime.manager import load_v3_profiles

        persona_dir = BUNDLES_DIR / pid / "persona"
        profiles = load_v3_profiles(persona_dir)
        assert profiles["persona_agent"] is not None
        assert profiles["manifest"] is not None
        assert profiles["cognitive"] is not None
        assert profiles["embodiment"] is not None
        assert profiles["vr_profile"] is not None
        assert profiles["voice"] is not None
        assert profiles["relationship"] is not None

    def test_build_with_defaults(self) -> None:
        """Building with minimal dicts should produce safe defaults."""
        from backend.app.persona_runtime.manager import build_runtime_config

        rc = build_runtime_config(
            persona_agent={"id": "test", "label": "Test"},
            manifest={"schema_version": 2},
        )
        assert rc.persona_id == "test"
        assert rc.is_v3 is False
        assert rc.is_vr_ready is False
        assert rc.is_orchestrated is False


# ── Motion DSL tests ─────────────────────────────────────────────────


class TestMotionDSL:
    """Test the embodiment.motion_dsl module."""

    def test_import(self) -> None:
        from backend.app.embodiment.motion_dsl import (
            CommandType,
            MotionCommand,
            MotionPlan,
            MotionPlanBuilder,
        )
        assert CommandType is not None
        assert MotionCommand is not None
        assert MotionPlan is not None
        assert MotionPlanBuilder is not None

    def test_builder_approach(self) -> None:
        from backend.app.embodiment.motion_dsl import MotionPlanBuilder

        plan = (
            MotionPlanBuilder("test")
            .approach("user", distance_m=1.2)
            .look_at("user_head")
            .build()
        )
        assert plan.persona_id == "test"
        assert len(plan.commands) == 2
        assert plan.commands[0].type == "approach"
        assert plan.commands[1].type == "look_at"

    def test_builder_follow(self) -> None:
        from backend.app.embodiment.motion_dsl import MotionPlanBuilder

        plan = MotionPlanBuilder("test").follow("user").look_at("user_head").build()
        assert any(c.type == "follow" for c in plan.commands)

    def test_plan_serialization(self) -> None:
        from backend.app.embodiment.motion_dsl import MotionPlanBuilder

        plan = MotionPlanBuilder("test").sit().look_at("user_head").build()
        d = plan.to_dict()
        assert "commands" in d
        assert isinstance(d["commands"], list)
        for cmd in d["commands"]:
            assert "type" in cmd

    def test_all_builder_methods(self) -> None:
        from backend.app.embodiment.motion_dsl import MotionPlanBuilder

        plan = (
            MotionPlanBuilder("test")
            .approach("user")
            .retreat()
            .look_at("user_head")
            .expression("smile")
            .gesture("wave")
            .follow("user")
            .stop()
            .sit()
            .stand()
            .wave()
            .nod()
            .point("target")
            .offer_hand()
            .idle()
            .priority("high")
            .not_interruptible()
            .build()
        )
        assert len(plan.commands) == 14
        assert plan.priority == "high"
        assert plan.interruptible is False


# ── Embodiment planner tests ─────────────────────────────────────────


class TestEmbodimentPlanner:
    """Test the embodiment.planner module."""

    def test_import(self) -> None:
        from backend.app.embodiment.planner import plan_from_utterance
        assert callable(plan_from_utterance)

    @pytest.mark.parametrize(
        "utterance",
        ["come here", "follow me", "stop", "sit down", "stand up",
         "look at me", "take my hand", "walk with me", "stay here",
         "come closer", "go away", "wave", "high five", "point"],
    )
    def test_all_standard_utterances(self, utterance: str) -> None:
        from backend.app.embodiment.planner import plan_from_utterance

        plan = plan_from_utterance(utterance, persona_id="test")
        assert plan is not None
        assert len(plan.commands) > 0

    def test_unknown_utterance_returns_none(self) -> None:
        from backend.app.embodiment.planner import plan_from_utterance

        plan = plan_from_utterance("do a backflip", persona_id="test")
        assert plan is None

    def test_come_here_produces_approach(self) -> None:
        from backend.app.embodiment.planner import plan_from_utterance

        plan = plan_from_utterance("come here", persona_id="test")
        assert plan.commands[0].type == "approach"


# ── World State tests ────────────────────────────────────────────────


class TestWorldState:
    """Test the world_state.service module."""

    def test_import(self) -> None:
        from backend.app.world_state.service import (
            Anchor,
            EntityState,
            Vector3,
            WorldStateService,
        )
        assert Vector3 is not None
        assert EntityState is not None
        assert Anchor is not None
        assert WorldStateService is not None

    def test_vector3_distance(self) -> None:
        from backend.app.world_state.service import Vector3

        a = Vector3(0, 0, 0)
        b = Vector3(3, 0, 4)
        assert abs(a.distance_to(b) - 5.0) < 0.01

    def test_world_state_service_crud(self) -> None:
        from backend.app.world_state.service import WorldStateService

        svc = WorldStateService()
        svc.update_user({"position": {"x": 1, "y": 0, "z": 2}})
        user = svc.get_user()
        assert user.position.x == 1.0
        assert user.position.z == 2.0

    def test_avatar_tracking(self) -> None:
        from backend.app.world_state.service import WorldStateService

        svc = WorldStateService()
        svc.update_avatar("scarlett", {"position": {"x": 2, "y": 0, "z": 3}, "state": "speaking"})
        av = svc.get_avatar("scarlett")
        assert av is not None
        assert av.state == "speaking"

    def test_anchors(self) -> None:
        from backend.app.world_state.service import WorldStateService

        svc = WorldStateService()
        svc.set_anchors([{"id": "chair1", "type": "seat", "position": {"x": 3, "y": 0, "z": 1}}])
        anchors = svc.get_anchors()
        assert len(anchors) == 1
        assert anchors[0].id == "chair1"

    def test_user_avatar_distance(self) -> None:
        from backend.app.world_state.service import WorldStateService

        svc = WorldStateService()
        svc.update_user({"position": {"x": 0, "y": 0, "z": 0}})
        svc.update_avatar("test", {"position": {"x": 3, "y": 0, "z": 4}})
        dist = svc.user_avatar_distance("test")
        assert dist is not None
        assert abs(dist - 5.0) < 0.01

    def test_snapshot(self) -> None:
        from backend.app.world_state.service import WorldStateService

        svc = WorldStateService()
        svc.update_user({"position": {"x": 1, "y": 0, "z": 0}})
        snap = svc.snapshot()
        assert "user" in snap
        assert "avatars" in snap
        assert "anchors" in snap
