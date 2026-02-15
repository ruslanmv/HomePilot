"""
Tests for persona export/import v2 (Phase 3 — must never break).

Validates:
  - v2 export produces full package (blueprint + dependencies + preview)
  - v2 import creates project with agentic data
  - Backward compat: v2 importer accepts v1 packages
  - Preview parses without creating a project
  - Dependency manifests are correctly built
  - Schema validation rejects future versions
  - Tool/MCP/agent manifests are populated from project data

Non-destructive: uses tmp_path + monkeypatched projects module.
CI-friendly: no network, no LLM, pure logic.
"""
import json
import zipfile
import io
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_PROJECTS_DB: dict = {}
_FAKE_COUNTER = 0


def _reset_fake_db():
    global _FAKE_PROJECTS_DB, _FAKE_COUNTER
    _FAKE_PROJECTS_DB = {}
    _FAKE_COUNTER = 0


def _fake_create_new_project(data: dict) -> dict:
    global _FAKE_COUNTER
    _FAKE_COUNTER += 1
    pid = f"imported-{_FAKE_COUNTER}"
    project = {
        "id": pid,
        "name": data.get("name", "Unnamed"),
        "description": data.get("description", ""),
        "project_type": data.get("project_type", "chat"),
        "is_public": data.get("is_public", False),
        "persona_agent": data.get("persona_agent", {}),
        "persona_appearance": data.get("persona_appearance", {}),
        "agentic": data.get("agentic", {}),
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    _FAKE_PROJECTS_DB[pid] = project
    return dict(project)


def _fake_update_project(project_id: str, data: dict) -> dict:
    if project_id not in _FAKE_PROJECTS_DB:
        return None
    proj = _FAKE_PROJECTS_DB[project_id]
    if "persona_appearance" in data:
        existing = proj.get("persona_appearance") or {}
        proj["persona_appearance"] = {**existing, **data["persona_appearance"]}
    _FAKE_PROJECTS_DB[project_id] = proj
    return dict(proj)


# ---------------------------------------------------------------------------
# v2 Export tests
# ---------------------------------------------------------------------------


class TestExportV2:
    """v2 export produces full package with dependencies."""

    def test_export_v2_structure(self, tmp_path: Path):
        from app.personas.export_import import export_persona_project

        upload_root = tmp_path / "uploads"
        upload_root.mkdir()

        project = {
            "id": "p1",
            "name": "Sakura",
            "project_type": "persona",
            "persona_agent": {
                "id": "sakura",
                "label": "Sakura",
                "system_prompt": "You are Sakura.",
                "allowed_tools": ["imagine", "search", "weather"],
                "category": "general",
            },
            "persona_appearance": {
                "style_preset": "Elegant",
                "aspect_ratio": "2:3",
                "img_model": "dreamshaper_8.safetensors",
                "avatar_settings": {
                    "img_model": "dreamshaper_8.safetensors",
                    "character_prompt": "anime girl",
                },
            },
            "agentic": {
                "goal": "Help with daily tasks",
                "capabilities": ["generate_images", "web_search"],
                "a2a_agent_ids": ["everyday-assistant"],
                "agent_details": {
                    "everyday-assistant": {
                        "name": "everyday-assistant",
                        "description": "Friendly helper",
                    },
                },
            },
        }

        result = export_persona_project(upload_root, project, mode="blueprint")

        assert result.filename == "Sakura.hpersona"
        assert len(result.data) > 0

        # Validate full v2 structure
        with zipfile.ZipFile(io.BytesIO(result.data), "r") as z:
            names = z.namelist()

            # Core
            assert "manifest.json" in names

            # Blueprint
            assert "blueprint/persona_agent.json" in names
            assert "blueprint/persona_appearance.json" in names
            assert "blueprint/agentic.json" in names

            # Dependencies
            assert "dependencies/tools.json" in names
            assert "dependencies/mcp_servers.json" in names
            assert "dependencies/a2a_agents.json" in names
            assert "dependencies/models.json" in names
            assert "dependencies/suite.json" in names

            # Preview
            assert "preview/card.json" in names

            # Validate manifest v2
            manifest = json.loads(z.read("manifest.json"))
            assert manifest["package_version"] == 2
            assert manifest["schema_version"] == 2
            assert manifest["kind"] == "homepilot.persona"
            assert manifest["contents"]["has_tool_dependencies"] is True
            assert "personality_tools" in manifest["capability_summary"]

            # Validate tools manifest
            tools = json.loads(z.read("dependencies/tools.json"))
            assert "imagine" in tools["personality_tools"]["tools"]
            assert "search" in tools["personality_tools"]["tools"]

            # Validate A2A manifest
            a2a = json.loads(z.read("dependencies/a2a_agents.json"))
            assert len(a2a["agents"]) == 1
            assert a2a["agents"][0]["name"] == "everyday-assistant"
            assert a2a["agents"][0]["source"]["type"] == "builtin"

            # Validate models manifest
            models = json.loads(z.read("dependencies/models.json"))
            assert len(models["image_models"]) == 1
            assert models["image_models"][0]["filename"] == "dreamshaper_8.safetensors"

            # Validate preview card
            card = json.loads(z.read("preview/card.json"))
            assert card["name"] == "Sakura"
            assert card["tools_count"] == 3

    def test_export_rejects_non_persona(self, tmp_path: Path):
        from app.personas.export_import import export_persona_project

        upload_root = tmp_path / "uploads"
        upload_root.mkdir()

        project = {"id": "x", "name": "Chat", "project_type": "chat"}
        with pytest.raises(ValueError, match="Not a persona project"):
            export_persona_project(upload_root, project)


# ---------------------------------------------------------------------------
# Preview tests
# ---------------------------------------------------------------------------


class TestPreview:
    """Preview parses package without creating a project."""

    def _make_v2_package(self, **overrides) -> bytes:
        manifest = {
            "package_version": 2,
            "schema_version": 2,
            "kind": "homepilot.persona",
            "content_rating": "sfw",
            "contents": {"has_avatar": False, "has_tool_dependencies": True},
        }
        agent = overrides.get("agent", {"id": "test", "label": "Test", "allowed_tools": ["imagine"]})
        appearance = overrides.get("appearance", {"style_preset": "Elegant"})
        agentic = overrides.get("agentic", {"goal": "Test goal", "capabilities": ["generate_images"]})

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("manifest.json", json.dumps(manifest))
            z.writestr("blueprint/persona_agent.json", json.dumps(agent))
            z.writestr("blueprint/persona_appearance.json", json.dumps(appearance))
            z.writestr("blueprint/agentic.json", json.dumps(agentic))
            z.writestr("dependencies/tools.json", json.dumps({
                "schema_version": 1,
                "personality_tools": {"tools": agent.get("allowed_tools", [])},
            }))
            z.writestr("dependencies/models.json", json.dumps({
                "schema_version": 1,
                "image_models": [],
            }))
        return buf.getvalue()

    def test_preview_returns_data(self):
        from app.personas.export_import import preview_persona_package

        pkg = self._make_v2_package()
        preview = preview_persona_package(pkg)

        assert preview.manifest["schema_version"] == 2
        assert preview.persona_agent["label"] == "Test"
        assert preview.agentic["goal"] == "Test goal"
        assert "tools" in preview.dependencies

    def test_preview_rejects_future_schema(self):
        from app.personas.export_import import preview_persona_package

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("manifest.json", json.dumps({
                "kind": "homepilot.persona",
                "schema_version": 999,
            }))
            z.writestr("blueprint/persona_agent.json", "{}")
            z.writestr("blueprint/persona_appearance.json", "{}")

        with pytest.raises(ValueError, match="newer than this HomePilot"):
            preview_persona_package(buf.getvalue())


# ---------------------------------------------------------------------------
# v2 Import tests
# ---------------------------------------------------------------------------


class TestImportV2:
    """v2 import creates project with agentic data."""

    def setup_method(self):
        _reset_fake_db()

    def _make_v2_package(self, agent=None, appearance=None, agentic=None) -> bytes:
        agent = agent or {"id": "imported", "label": "Imported Bot", "allowed_tools": ["imagine"]}
        appearance = appearance or {"style_preset": "Elegant"}
        agentic = agentic or {"goal": "Help the user", "capabilities": ["generate_images"]}
        manifest = {
            "package_version": 2,
            "schema_version": 2,
            "kind": "homepilot.persona",
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("manifest.json", json.dumps(manifest))
            z.writestr("blueprint/persona_agent.json", json.dumps(agent))
            z.writestr("blueprint/persona_appearance.json", json.dumps(appearance))
            z.writestr("blueprint/agentic.json", json.dumps(agentic))
        return buf.getvalue()

    def test_import_v2_creates_project_with_agentic(self, tmp_path: Path, monkeypatch):
        from app.personas import export_import

        monkeypatch.setattr(export_import.projects, "create_new_project", _fake_create_new_project)
        monkeypatch.setattr(export_import.projects, "update_project", _fake_update_project)

        upload_root = tmp_path / "uploads"
        upload_root.mkdir()

        pkg = self._make_v2_package(
            agentic={"goal": "Be helpful", "capabilities": ["web_search"]},
        )
        created = export_import.import_persona_package(upload_root, pkg)

        assert created["project_type"] == "persona"
        assert created["agentic"]["goal"] == "Be helpful"
        assert "web_search" in created["agentic"]["capabilities"]

    def test_import_v1_backward_compat(self, tmp_path: Path, monkeypatch):
        """v2 importer should accept v1 packages (no dependencies/ or agentic)."""
        from app.personas import export_import

        monkeypatch.setattr(export_import.projects, "create_new_project", _fake_create_new_project)
        monkeypatch.setattr(export_import.projects, "update_project", _fake_update_project)

        upload_root = tmp_path / "uploads"
        upload_root.mkdir()

        # Build a v1 package (no agentic, no dependencies)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("manifest.json", json.dumps({
                "package_version": 1,
                "schema_version": 1,
                "kind": "homepilot.persona",
            }))
            z.writestr("blueprint/persona_agent.json", json.dumps({"label": "OldBot"}))
            z.writestr("blueprint/persona_appearance.json", json.dumps({"style_preset": "Casual"}))

        created = export_import.import_persona_package(upload_root, buf.getvalue())

        assert created["project_type"] == "persona"
        assert created["name"] == "OldBot"
        assert created.get("agentic", {}) == {}  # no agentic in v1


# ---------------------------------------------------------------------------
# Dependency checker tests
# ---------------------------------------------------------------------------


class TestDependencyChecker:
    """Dependency checker reports correctly."""

    def test_empty_dependencies(self):
        from app.personas.dependency_checker import check_dependencies

        report = check_dependencies({})
        assert report.all_satisfied is True
        assert report.summary == "No dependencies required"

    def test_builtin_tools_available(self):
        from app.personas.dependency_checker import check_dependencies

        deps = {
            "tools": {
                "personality_tools": {"tools": ["imagine", "search"]},
            },
        }
        report = check_dependencies(deps)
        tool_names = [t.name for t in report.tools]
        assert "imagine" in tool_names
        assert "search" in tool_names
        # These are built-in tools, should be available
        assert all(t.status == "available" for t in report.tools)

    def test_builtin_mcp_servers(self):
        from app.personas.dependency_checker import check_dependencies

        deps = {
            "mcp_servers": {
                "servers": [
                    {
                        "name": "hp-personal-assistant",
                        "source": {"type": "builtin"},
                        "default_port": 9101,
                    },
                ],
            },
        }
        report = check_dependencies(deps)
        assert len(report.mcp_servers) == 1
        assert report.mcp_servers[0].status == "available"
        assert report.mcp_servers[0].source_type == "builtin"

    def test_external_mcp_server_unknown(self):
        from app.personas.dependency_checker import check_dependencies

        deps = {
            "mcp_servers": {
                "servers": [
                    {
                        "name": "custom-weather",
                        "source": {"type": "external"},
                    },
                ],
            },
        }
        report = check_dependencies(deps)
        assert len(report.mcp_servers) == 1
        assert report.mcp_servers[0].status == "unknown"
        assert report.mcp_servers[0].source_type == "external"

    def test_builtin_a2a_agents(self):
        from app.personas.dependency_checker import check_dependencies

        deps = {
            "a2a_agents": {
                "agents": [
                    {
                        "name": "everyday-assistant",
                        "source": {"type": "builtin"},
                        "default_port": 9201,
                    },
                ],
            },
        }
        report = check_dependencies(deps)
        assert len(report.a2a_agents) == 1
        assert report.a2a_agents[0].status == "available"


# ---------------------------------------------------------------------------
# Roundtrip tests
# ---------------------------------------------------------------------------


class TestRoundtripV2:
    """v2 export then import preserves all data."""

    def setup_method(self):
        _reset_fake_db()

    def test_full_roundtrip(self, tmp_path: Path, monkeypatch):
        from app.personas.export_import import export_persona_project, import_persona_package
        from app.personas import export_import

        monkeypatch.setattr(export_import.projects, "create_new_project", _fake_create_new_project)
        monkeypatch.setattr(export_import.projects, "update_project", _fake_update_project)

        upload_root = tmp_path / "uploads"
        upload_root.mkdir()

        original = {
            "id": "rt-v2",
            "name": "RoundtripV2",
            "project_type": "persona",
            "persona_agent": {
                "id": "rt",
                "label": "RoundtripV2",
                "system_prompt": "You are a helpful bot.",
                "allowed_tools": ["imagine", "search"],
                "category": "general",
            },
            "persona_appearance": {
                "style_preset": "Elegant",
                "aspect_ratio": "2:3",
            },
            "agentic": {
                "goal": "Help with everything",
                "capabilities": ["generate_images", "web_search"],
                "a2a_agent_ids": ["everyday-assistant"],
                "agent_details": {
                    "everyday-assistant": {"name": "everyday-assistant"},
                },
            },
        }

        exported = export_persona_project(upload_root, original, mode="blueprint")
        imported = import_persona_package(upload_root, exported.data)

        assert imported["project_type"] == "persona"
        assert imported["persona_agent"]["label"] == "RoundtripV2"
        assert imported["persona_agent"]["allowed_tools"] == ["imagine", "search"]
        assert imported["agentic"]["goal"] == "Help with everything"
        assert "everyday-assistant" in imported["agentic"]["a2a_agent_ids"]
