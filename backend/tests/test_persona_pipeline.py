"""
Tests for community/scripts/process_submission.py

Covers the three CLI sub-commands used by the persona-publish GitHub Action:
  - validate  : ZIP integrity, manifest schema, path-traversal rejection
  - extract   : metadata + preview image extraction
  - registry  : upsert / remove entries in registry.json

All tests use only stdlib — no network, no external services.
"""
from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

import pytest

# Import the module under test.  It lives outside the backend package tree,
# so we add its parent to sys.path.
import sys

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "community" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
import process_submission as ps  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers — build .hpersona test fixtures
# ---------------------------------------------------------------------------

def _make_hpersona(
    *,
    label: str = "TestPersona",
    schema_version: int = 2,
    kind: str = "homepilot.persona",
    content_rating: str = "sfw",
    include_agentic: bool = True,
    include_deps: bool = True,
    include_card: bool = True,
    include_avatar: bool = False,
    extra_files: dict[str, bytes] | None = None,
    bad_manifest_json: bool = False,
) -> bytes:
    """Build a minimal .hpersona ZIP in memory."""
    manifest = {
        "package_version": 2,
        "schema_version": schema_version,
        "kind": kind,
        "content_rating": content_rating,
        "contents": {
            "has_avatar": include_avatar,
            "has_tool_dependencies": False,
        },
    }
    agent = {
        "id": "test",
        "label": label,
        "system_prompt": f"You are {label}.",
        "allowed_tools": ["web_search"],
        "role": "assistant",
        "category": "general",
        "response_style": {"tone": "friendly"},
    }
    appearance = {
        "style_preset": "Elegant",
        "aspect_ratio": "2:3",
        "nsfwMode": content_rating == "nsfw",
    }
    agentic = {"goal": "Help the user", "capabilities": ["generate_images"]}
    card = {
        "name": label,
        "role": "assistant",
        "category": "general",
        "tone": "friendly",
        "content_rating": content_rating,
    }
    tools_dep = {"schema_version": 1, "personality_tools": {"tools": ["web_search"]}}
    mcp_dep = {"schema_version": 1, "servers": []}
    a2a_dep = {"schema_version": 1, "agents": []}
    models_dep = {"schema_version": 1, "image_models": []}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        if bad_manifest_json:
            z.writestr("manifest.json", "{not valid json!!!")
        else:
            z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("blueprint/persona_agent.json", json.dumps(agent))
        z.writestr("blueprint/persona_appearance.json", json.dumps(appearance))
        if include_agentic:
            z.writestr("blueprint/agentic.json", json.dumps(agentic))
        if include_deps:
            z.writestr("dependencies/tools.json", json.dumps(tools_dep))
            z.writestr("dependencies/mcp_servers.json", json.dumps(mcp_dep))
            z.writestr("dependencies/a2a_agents.json", json.dumps(a2a_dep))
            z.writestr("dependencies/models.json", json.dumps(models_dep))
        if include_card:
            z.writestr("preview/card.json", json.dumps(card))
        if include_avatar:
            # 1x1 white PNG (smallest valid PNG)
            z.writestr("assets/avatar_test.webp", b"\x00" * 64)
        if extra_files:
            for name, data in extra_files.items():
                z.writestr(name, data)

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests: validate_package
# ---------------------------------------------------------------------------


class TestValidatePackage:
    """Validation of .hpersona ZIP packages."""

    def test_valid_v2_package(self, tmp_path):
        """A well-formed v2 package passes validation."""
        pkg = tmp_path / "test.hpersona"
        pkg.write_bytes(_make_hpersona())

        result = ps.validate_package(pkg)

        assert result["valid"] is True
        assert result["errors"] == []
        assert result["manifest"]["kind"] == "homepilot.persona"
        assert result["manifest"]["schema_version"] == 2
        assert isinstance(result["sha256"], str) and len(result["sha256"]) == 64
        assert result["size_bytes"] > 0

    def test_valid_v1_package(self, tmp_path):
        """A v1 package (no deps, no agentic) still passes."""
        pkg = tmp_path / "v1.hpersona"
        pkg.write_bytes(_make_hpersona(schema_version=1, include_deps=False, include_agentic=False))

        result = ps.validate_package(pkg)

        assert result["valid"] is True
        assert result["errors"] == []

    def test_not_a_zip(self, tmp_path):
        """Random bytes are rejected."""
        pkg = tmp_path / "bad.hpersona"
        pkg.write_bytes(b"this is not a zip file at all")

        result = ps.validate_package(pkg)

        assert result["valid"] is False
        assert any("not a valid ZIP" in e for e in result["errors"])

    def test_missing_manifest(self, tmp_path):
        """ZIP without manifest.json is rejected."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("blueprint/persona_agent.json", "{}")
            z.writestr("blueprint/persona_appearance.json", "{}")
        pkg = tmp_path / "no_manifest.hpersona"
        pkg.write_bytes(buf.getvalue())

        result = ps.validate_package(pkg)

        assert result["valid"] is False
        assert any("manifest.json" in e for e in result["errors"])

    def test_missing_blueprint_files(self, tmp_path):
        """ZIP with manifest but missing blueprint files is rejected."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("manifest.json", json.dumps({
                "schema_version": 2, "kind": "homepilot.persona"
            }))
        pkg = tmp_path / "no_blueprint.hpersona"
        pkg.write_bytes(buf.getvalue())

        result = ps.validate_package(pkg)

        assert result["valid"] is False
        assert any("persona_agent.json" in e for e in result["errors"])

    def test_invalid_manifest_json(self, tmp_path):
        """Corrupt manifest JSON is rejected."""
        pkg = tmp_path / "bad_json.hpersona"
        pkg.write_bytes(_make_hpersona(bad_manifest_json=True))

        result = ps.validate_package(pkg)

        assert result["valid"] is False
        assert any("not valid JSON" in e for e in result["errors"])

    def test_wrong_kind(self, tmp_path):
        """Package with wrong kind is rejected."""
        pkg = tmp_path / "wrong_kind.hpersona"
        pkg.write_bytes(_make_hpersona(kind="homepilot.agent"))

        result = ps.validate_package(pkg)

        assert result["valid"] is False
        assert any("Invalid kind" in e for e in result["errors"])

    def test_schema_version_too_high(self, tmp_path):
        """Schema version beyond MAX is rejected."""
        pkg = tmp_path / "future.hpersona"
        pkg.write_bytes(_make_hpersona(schema_version=99))

        result = ps.validate_package(pkg)

        assert result["valid"] is False
        assert any("not supported" in e for e in result["errors"])

    def test_schema_version_zero(self, tmp_path):
        """Schema version 0 is rejected."""
        pkg = tmp_path / "zero.hpersona"
        pkg.write_bytes(_make_hpersona(schema_version=0))

        result = ps.validate_package(pkg)

        assert result["valid"] is False
        assert any(">= 1" in e for e in result["errors"])

    def test_path_traversal_rejected(self, tmp_path):
        """Paths with .. are flagged as errors."""
        pkg = tmp_path / "traversal.hpersona"
        pkg.write_bytes(_make_hpersona(extra_files={"../../etc/passwd": b"root:x:0:0"}))

        result = ps.validate_package(pkg)

        assert result["valid"] is False
        assert any("Suspicious path" in e for e in result["errors"])

    def test_oversized_package_rejected(self, tmp_path, monkeypatch):
        """Package exceeding MAX_PACKAGE_SIZE is rejected."""
        monkeypatch.setattr(ps, "MAX_PACKAGE_SIZE", 100)  # 100 bytes

        pkg = tmp_path / "huge.hpersona"
        pkg.write_bytes(_make_hpersona())  # certainly > 100 bytes

        result = ps.validate_package(pkg)

        assert result["valid"] is False
        assert any("too large" in e for e in result["errors"])

    def test_missing_deps_produces_warnings(self, tmp_path):
        """v2 package without dependencies/ files produces warnings, not errors."""
        pkg = tmp_path / "nodeps.hpersona"
        pkg.write_bytes(_make_hpersona(include_deps=False))

        result = ps.validate_package(pkg)

        assert result["valid"] is True
        assert any("Missing optional dependency" in w for w in result["warnings"])

    def test_unexpected_asset_extension_produces_warning(self, tmp_path):
        """Non-image file in assets/ produces a warning."""
        pkg = tmp_path / "odd_asset.hpersona"
        pkg.write_bytes(_make_hpersona(extra_files={"assets/readme.txt": b"hello"}))

        result = ps.validate_package(pkg)

        assert result["valid"] is True
        assert any("Unexpected asset type" in w for w in result["warnings"])

    def test_empty_label_produces_warning(self, tmp_path):
        """Agent with empty label produces a warning."""
        pkg = tmp_path / "empty_label.hpersona"
        pkg.write_bytes(_make_hpersona(label=""))

        result = ps.validate_package(pkg)

        assert result["valid"] is True
        assert any("label is empty" in w for w in result["warnings"])

    def test_nsfw_content_rating(self, tmp_path):
        """NSFW content rating in manifest is preserved in validation."""
        pkg = tmp_path / "nsfw.hpersona"
        pkg.write_bytes(_make_hpersona(content_rating="nsfw"))

        result = ps.validate_package(pkg)

        assert result["valid"] is True
        assert result["manifest"]["content_rating"] == "nsfw"

    def test_sha256_is_consistent(self, tmp_path):
        """SHA-256 hash is deterministic for the same bytes."""
        data = _make_hpersona()
        pkg1 = tmp_path / "a.hpersona"
        pkg2 = tmp_path / "b.hpersona"
        pkg1.write_bytes(data)
        pkg2.write_bytes(data)

        r1 = ps.validate_package(pkg1)
        r2 = ps.validate_package(pkg2)

        assert r1["sha256"] == r2["sha256"]


# ---------------------------------------------------------------------------
# Tests: extract_metadata
# ---------------------------------------------------------------------------


class TestExtractMetadata:
    """Metadata and preview extraction from .hpersona packages."""

    def test_extracts_card_json(self, tmp_path):
        """Writes card.json to output directory."""
        pkg = tmp_path / "test.hpersona"
        pkg.write_bytes(_make_hpersona(label="Atlas"))
        out = tmp_path / "out"

        result = ps.extract_metadata(pkg, out)

        assert (out / "card.json").exists()
        card = json.loads((out / "card.json").read_text())
        assert card["name"] == "Atlas"
        assert card["content_rating"] == "sfw"
        assert card["tools_count"] == 1  # web_search

    def test_extracts_preview_image(self, tmp_path):
        """Avatar from assets/ is extracted as preview."""
        pkg = tmp_path / "test.hpersona"
        pkg.write_bytes(_make_hpersona(include_avatar=True))
        out = tmp_path / "out"

        result = ps.extract_metadata(pkg, out)

        assert result["preview_extracted"] is True
        # Should have a preview file with image extension
        preview_files = [f for f in out.iterdir() if f.name.startswith("preview")]
        assert len(preview_files) >= 1

    def test_no_avatar_means_no_preview(self, tmp_path):
        """No avatar in assets/ means no preview file extracted."""
        pkg = tmp_path / "test.hpersona"
        pkg.write_bytes(_make_hpersona(include_avatar=False))
        out = tmp_path / "out"

        result = ps.extract_metadata(pkg, out)

        assert result["preview_extracted"] is False

    def test_generates_card_without_preview_card(self, tmp_path):
        """When preview/card.json is missing, card is built from blueprint."""
        pkg = tmp_path / "test.hpersona"
        pkg.write_bytes(_make_hpersona(include_card=False, label="Minerva"))
        out = tmp_path / "out"

        result = ps.extract_metadata(pkg, out)

        card = result["card"]
        assert card["name"] == "Minerva"
        assert card["content_rating"] == "sfw"

    def test_sha256_and_size_in_result(self, tmp_path):
        """Result includes sha256 and size_bytes."""
        pkg = tmp_path / "test.hpersona"
        data = _make_hpersona()
        pkg.write_bytes(data)
        out = tmp_path / "out"

        result = ps.extract_metadata(pkg, out)

        assert len(result["sha256"]) == 64
        assert result["size_bytes"] == len(data)

    def test_capabilities_count(self, tmp_path):
        """Card includes capabilities count from agentic data."""
        pkg = tmp_path / "test.hpersona"
        pkg.write_bytes(_make_hpersona(include_agentic=True))
        out = tmp_path / "out"

        result = ps.extract_metadata(pkg, out)

        assert result["card"]["capabilities_count"] == 1  # generate_images

    def test_creates_output_directory(self, tmp_path):
        """Output directory is created if it doesn't exist."""
        pkg = tmp_path / "test.hpersona"
        pkg.write_bytes(_make_hpersona())
        out = tmp_path / "deep" / "nested" / "output"

        ps.extract_metadata(pkg, out)

        assert out.exists()
        assert (out / "card.json").exists()


# ---------------------------------------------------------------------------
# Tests: update_registry
# ---------------------------------------------------------------------------


class TestUpdateRegistry:
    """Registry upsert and remove operations."""

    def _make_entry(self, id: str = "atlas", name: str = "Atlas", **kwargs) -> dict:
        return {
            "id": id,
            "name": name,
            "short": f"{name} persona",
            "tags": ["professional"],
            "nsfw": False,
            "author": "tester",
            "issue_number": 1,
            "submitted_at": "2026-02-15T00:00:00Z",
            "downloads": 0,
            "latest": {
                "version": "1.0.0",
                "package_url": f"https://example.com/{id}.hpersona",
                "preview_url": "",
                "sha256": "abc",
                "size_bytes": 1024,
            },
            **kwargs,
        }

    def test_creates_new_registry(self, tmp_path):
        """Registry file is created from scratch when it doesn't exist."""
        reg = tmp_path / "registry.json"
        entry = self._make_entry()

        result = ps.update_registry(reg, entry)

        assert reg.exists()
        assert result["total"] == 1
        data = json.loads(reg.read_text())
        assert data["schema_version"] == 1
        assert data["source"] == "github-pages"
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == "atlas"

    def test_upsert_adds_new_entry(self, tmp_path):
        """Adding a new persona to existing registry."""
        reg = tmp_path / "registry.json"
        reg.write_text(json.dumps({
            "schema_version": 1, "generated_at": "", "source": "github-pages",
            "total": 1,
            "items": [self._make_entry("scarlett", "Scarlett")],
        }))

        result = ps.update_registry(reg, self._make_entry("atlas", "Atlas"))

        assert result["total"] == 2
        data = json.loads(reg.read_text())
        ids = [i["id"] for i in data["items"]]
        assert "atlas" in ids
        assert "scarlett" in ids

    def test_upsert_replaces_existing_entry(self, tmp_path):
        """Same persona ID overwrites the old entry."""
        reg = tmp_path / "registry.json"
        reg.write_text(json.dumps({
            "schema_version": 1, "generated_at": "", "source": "github-pages",
            "total": 1,
            "items": [self._make_entry("atlas", "Atlas v1")],
        }))

        result = ps.update_registry(reg, self._make_entry("atlas", "Atlas v2"))

        assert result["total"] == 1
        data = json.loads(reg.read_text())
        assert data["items"][0]["name"] == "Atlas v2"

    def test_remove_entry(self, tmp_path):
        """Removing an entry by ID."""
        reg = tmp_path / "registry.json"
        reg.write_text(json.dumps({
            "schema_version": 1, "generated_at": "", "source": "github-pages",
            "total": 2,
            "items": [
                self._make_entry("atlas", "Atlas"),
                self._make_entry("scarlett", "Scarlett"),
            ],
        }))

        result = ps.update_registry(reg, {}, remove_id="atlas")

        assert result["total"] == 1
        data = json.loads(reg.read_text())
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == "scarlett"

    def test_remove_nonexistent_is_no_op(self, tmp_path):
        """Removing a non-existent ID doesn't crash or change count."""
        reg = tmp_path / "registry.json"
        reg.write_text(json.dumps({
            "schema_version": 1, "generated_at": "", "source": "github-pages",
            "total": 1,
            "items": [self._make_entry("atlas", "Atlas")],
        }))

        result = ps.update_registry(reg, {}, remove_id="nonexistent")

        assert result["total"] == 1

    def test_items_sorted_by_name(self, tmp_path):
        """After upsert, items are sorted alphabetically by name."""
        reg = tmp_path / "registry.json"
        ps.update_registry(reg, self._make_entry("z_persona", "Zara"))
        ps.update_registry(reg, self._make_entry("a_persona", "Alice"))
        ps.update_registry(reg, self._make_entry("m_persona", "Mira"))

        data = json.loads(reg.read_text())
        names = [i["name"] for i in data["items"]]
        assert names == ["Alice", "Mira", "Zara"]

    def test_generated_at_updated(self, tmp_path):
        """Each update refreshes the generated_at timestamp."""
        reg = tmp_path / "registry.json"
        ps.update_registry(reg, self._make_entry())

        data1 = json.loads(reg.read_text())
        ts1 = data1["generated_at"]
        assert ts1  # non-empty

        ps.update_registry(reg, self._make_entry("scarlett", "Scarlett"))
        data2 = json.loads(reg.read_text())
        ts2 = data2["generated_at"]
        assert ts2  # non-empty


# ---------------------------------------------------------------------------
# Tests: slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    """Name-to-slug conversion for persona IDs."""

    def test_basic_name(self):
        assert ps.slugify("Scarlett") == "scarlett"

    def test_multi_word(self):
        assert ps.slugify("My Cool Persona") == "my_cool_persona"

    def test_special_characters(self):
        assert ps.slugify("Héllo Wörld!") == "h_llo_w_rld"

    def test_leading_trailing_underscores(self):
        assert ps.slugify("  --test--  ") == "test"

    def test_empty_string(self):
        assert ps.slugify("") == "persona"

    def test_all_special_chars(self):
        assert ps.slugify("@#$%^&*") == "persona"

    def test_numbers_preserved(self):
        assert ps.slugify("Agent 007") == "agent_007"


# ---------------------------------------------------------------------------
# Tests: CLI entry point
# ---------------------------------------------------------------------------


class TestCLI:
    """CLI interface (main function)."""

    def test_no_args_returns_2(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["process_submission.py"])
        assert ps.main() == 2

    def test_unknown_command_returns_2(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["process_submission.py", "foobar"])
        assert ps.main() == 2

    def test_validate_valid_package(self, tmp_path, monkeypatch, capsys):
        pkg = tmp_path / "test.hpersona"
        pkg.write_bytes(_make_hpersona())
        monkeypatch.setattr(sys, "argv", ["process_submission.py", "validate", str(pkg)])

        rc = ps.main()
        out = capsys.readouterr().out

        assert rc == 0
        result = json.loads(out)
        assert result["valid"] is True

    def test_validate_invalid_package(self, tmp_path, monkeypatch, capsys):
        pkg = tmp_path / "bad.hpersona"
        pkg.write_bytes(b"not a zip")
        monkeypatch.setattr(sys, "argv", ["process_submission.py", "validate", str(pkg)])

        rc = ps.main()
        out = capsys.readouterr().out

        assert rc == 1
        result = json.loads(out)
        assert result["valid"] is False

    def test_extract_command(self, tmp_path, monkeypatch, capsys):
        pkg = tmp_path / "test.hpersona"
        pkg.write_bytes(_make_hpersona())
        out_dir = tmp_path / "extracted"
        monkeypatch.setattr(sys, "argv", [
            "process_submission.py", "extract", str(pkg), str(out_dir)
        ])

        rc = ps.main()

        assert rc == 0
        assert (out_dir / "card.json").exists()

    def test_registry_command(self, tmp_path, monkeypatch, capsys):
        reg = tmp_path / "registry.json"
        entry_file = tmp_path / "entry.json"
        entry_file.write_text(json.dumps({
            "id": "test", "name": "Test", "tags": [], "nsfw": False,
            "latest": {"version": "1.0.0"},
        }))
        monkeypatch.setattr(sys, "argv", [
            "process_submission.py", "registry", str(reg), str(entry_file)
        ])

        rc = ps.main()
        out = capsys.readouterr().out

        assert rc == 0
        result = json.loads(out)
        assert result["ok"] is True
        assert result["total"] == 1


# ---------------------------------------------------------------------------
# Tests: GitHub Actions workflow YAML structure
# ---------------------------------------------------------------------------


class TestWorkflowIntegrity:
    """Verify the GitHub Actions workflow file structure."""

    @pytest.fixture
    def workflow(self):
        workflow_path = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "persona-publish.yml"
        import yaml
        with open(workflow_path) as f:
            return yaml.safe_load(f)

    def test_workflow_file_exists(self):
        path = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "persona-publish.yml"
        assert path.exists(), "persona-publish.yml workflow must exist"

    def test_triggers_on_issue_labeled(self, workflow):
        # YAML parses bare `on` as boolean True; use True as key
        trigger = workflow.get("on") or workflow.get(True, {})
        assert "issues" in trigger
        assert "labeled" in trigger["issues"]["types"]

    def test_requires_persona_approved_label(self, workflow):
        job = workflow["jobs"]["publish"]
        assert "persona-approved" in job["if"]

    def test_has_contents_write_permission(self, workflow):
        permissions = workflow.get("permissions", {})
        assert permissions.get("contents") == "write"
        assert permissions.get("issues") == "write"

    def test_has_failure_notification_step(self, workflow):
        steps = workflow["jobs"]["publish"]["steps"]
        step_names = [s.get("name", "") for s in steps]
        assert any("failure" in n.lower() or "fail" in n.lower() for n in step_names)


# ---------------------------------------------------------------------------
# Tests: Issue template structure
# ---------------------------------------------------------------------------


class TestIssueTemplateIntegrity:
    """Verify the issue template YAML structure."""

    @pytest.fixture
    def template(self):
        path = Path(__file__).resolve().parent.parent.parent / ".github" / "ISSUE_TEMPLATE" / "persona-submission.yml"
        import yaml
        with open(path) as f:
            return yaml.safe_load(f)

    def test_template_file_exists(self):
        path = Path(__file__).resolve().parent.parent.parent / ".github" / "ISSUE_TEMPLATE" / "persona-submission.yml"
        assert path.exists(), "persona-submission.yml template must exist"

    def test_has_persona_submission_label(self, template):
        assert "persona-submission" in template["labels"]

    def test_has_required_fields(self, template):
        field_ids = [item.get("id") for item in template["body"] if item.get("type") != "markdown"]
        assert "persona_name" in field_ids
        assert "short_description" in field_ids
        assert "tags" in field_ids
        assert "content_rating" in field_ids
        assert "package_file" in field_ids

    def test_persona_name_is_required(self, template):
        for item in template["body"]:
            if item.get("id") == "persona_name":
                assert item["validations"]["required"] is True
                break

    def test_agreements_checkboxes_exist(self, template):
        for item in template["body"]:
            if item.get("id") == "agreements":
                assert item["type"] == "checkboxes"
                opts = item["attributes"]["options"]
                assert len(opts) >= 1
                assert all(o["required"] for o in opts)
                break


# ---------------------------------------------------------------------------
# Tests: Gallery HTML + JS integrity
# ---------------------------------------------------------------------------


class TestGalleryFiles:
    """Verify gallery static files exist and contain expected content."""

    def test_gallery_html_exists(self):
        path = Path(__file__).resolve().parent.parent.parent / "docs" / "gallery.html"
        assert path.exists()

    def test_gallery_html_has_search(self):
        path = Path(__file__).resolve().parent.parent.parent / "docs" / "gallery.html"
        content = path.read_text()
        assert 'id="search"' in content
        assert 'id="filter-tag"' in content
        assert 'id="filter-rating"' in content

    def test_gallery_html_has_submit_link(self):
        path = Path(__file__).resolve().parent.parent.parent / "docs" / "gallery.html"
        content = path.read_text()
        assert "persona-submission.yml" in content

    def test_gallery_js_exists(self):
        path = Path(__file__).resolve().parent.parent.parent / "docs" / "gallery.js"
        assert path.exists()

    def test_gallery_js_fetches_registry(self):
        path = Path(__file__).resolve().parent.parent.parent / "docs" / "gallery.js"
        content = path.read_text()
        assert "registry.json" in content

    def test_gallery_js_renders_cards(self):
        path = Path(__file__).resolve().parent.parent.parent / "docs" / "gallery.js"
        content = path.read_text()
        assert "renderCard" in content

    def test_registry_json_exists_and_valid(self):
        path = Path(__file__).resolve().parent.parent.parent / "docs" / "registry.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["schema_version"] == 1
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_index_html_links_to_gallery(self):
        path = Path(__file__).resolve().parent.parent.parent / "docs" / "index.html"
        content = path.read_text()
        assert "gallery.html" in content
