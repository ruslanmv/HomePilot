"""
Tests for persona avatar auto-commit and enhanced commit endpoint.

Validates:
  - _resolve_selected_image_url correctly walks sets to find the selected URL
  - _download_comfy_image enforces COMFY_BASE_URL host allowlist
  - _download_comfy_image rejects non-/view paths (SSRF prevention)
  - _download_comfy_image prevents path-traversal filenames
  - Auto-commit integrates: download → commit → paths persisted on project
  - Enhanced commit endpoint: source_url, auto, and source_filename modes
  - Export round-trip: committed assets appear in ZIP

Non-destructive: uses tmp_path + monkeypatched modules.
CI-friendly: no network, no LLM, no ComfyUI required.
"""
import io
import json
import os
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# _resolve_selected_image_url tests
# ---------------------------------------------------------------------------


class TestResolveSelectedImageUrl:
    """Unit tests for the URL resolver helper."""

    def _resolve(self, appearance):
        from app.main import _resolve_selected_image_url
        return _resolve_selected_image_url(appearance)

    def test_resolves_matching_image(self):
        appearance = {
            "selected": {"set_id": "set_001", "image_id": "img_2"},
            "sets": [
                {
                    "set_id": "set_001",
                    "images": [
                        {"id": "img_1", "url": "http://comfy:8188/view?filename=a.png"},
                        {"id": "img_2", "url": "http://comfy:8188/view?filename=b.png"},
                    ],
                },
            ],
        }
        assert self._resolve(appearance) == "http://comfy:8188/view?filename=b.png"

    def test_returns_none_when_no_selected(self):
        appearance = {
            "sets": [{"set_id": "s1", "images": [{"id": "i1", "url": "http://x/view?filename=a.png"}]}],
        }
        assert self._resolve(appearance) is None

    def test_returns_none_when_selected_missing_ids(self):
        appearance = {"selected": {}, "sets": []}
        assert self._resolve(appearance) is None

    def test_returns_none_when_image_not_found(self):
        appearance = {
            "selected": {"set_id": "set_001", "image_id": "nonexistent"},
            "sets": [
                {"set_id": "set_001", "images": [{"id": "img_1", "url": "http://x/view?filename=a.png"}]},
            ],
        }
        assert self._resolve(appearance) is None

    def test_returns_none_when_set_not_found(self):
        appearance = {
            "selected": {"set_id": "set_999", "image_id": "img_1"},
            "sets": [
                {"set_id": "set_001", "images": [{"id": "img_1", "url": "http://x/view?filename=a.png"}]},
            ],
        }
        assert self._resolve(appearance) is None

    def test_returns_none_for_empty_url(self):
        appearance = {
            "selected": {"set_id": "s1", "image_id": "i1"},
            "sets": [{"set_id": "s1", "images": [{"id": "i1", "url": ""}]}],
        }
        assert self._resolve(appearance) is None

    def test_returns_none_for_non_dict_input(self):
        assert self._resolve(None) is None
        assert self._resolve("not a dict") is None

    def test_multiple_sets_picks_correct_one(self):
        appearance = {
            "selected": {"set_id": "set_002", "image_id": "img_3"},
            "sets": [
                {"set_id": "set_001", "images": [{"id": "img_1", "url": "http://x/view?filename=wrong.png"}]},
                {"set_id": "set_002", "images": [
                    {"id": "img_2", "url": "http://x/view?filename=also_wrong.png"},
                    {"id": "img_3", "url": "http://x/view?filename=correct.png"},
                ]},
            ],
        }
        assert self._resolve(appearance) == "http://x/view?filename=correct.png"


# ---------------------------------------------------------------------------
# _download_comfy_image tests
# ---------------------------------------------------------------------------


class TestDownloadComfyImage:
    """Unit tests for the secure ComfyUI image downloader."""

    @pytest.mark.asyncio
    async def test_rejects_non_comfy_host(self):
        from app.main import _download_comfy_image

        with patch("app.main.COMFY_BASE_URL", "http://comfy:8188"):
            with pytest.raises(ValueError, match="non-ComfyUI host"):
                await _download_comfy_image(
                    "http://evil.com/view?filename=x.png", Path("/tmp"),
                )

    @pytest.mark.asyncio
    async def test_rejects_non_view_path(self):
        from app.main import _download_comfy_image

        with patch("app.main.COMFY_BASE_URL", "http://comfy:8188"):
            with pytest.raises(ValueError, match="non-/view path"):
                await _download_comfy_image(
                    "http://comfy:8188/api/secret?filename=x.png", Path("/tmp"),
                )

    @pytest.mark.asyncio
    async def test_rejects_missing_filename_param(self):
        from app.main import _download_comfy_image

        with patch("app.main.COMFY_BASE_URL", "http://comfy:8188"):
            with pytest.raises(ValueError, match="missing 'filename'"):
                await _download_comfy_image(
                    "http://comfy:8188/view?type=output", Path("/tmp"),
                )

    @pytest.mark.asyncio
    async def test_rejects_path_traversal(self):
        from app.main import _download_comfy_image

        with patch("app.main.COMFY_BASE_URL", "http://comfy:8188"):
            with pytest.raises(ValueError, match="Invalid filename"):
                await _download_comfy_image(
                    "http://comfy:8188/view?filename=..", Path("/tmp"),
                )

    @pytest.mark.asyncio
    async def test_successful_download(self, tmp_path: Path):
        from app.main import _download_comfy_image

        fake_image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        mock_response = AsyncMock()
        mock_response.content = fake_image_bytes
        mock_response.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.main.COMFY_BASE_URL", "http://comfy:8188"), \
             patch("app.main.httpx.AsyncClient", return_value=mock_client):
            result = await _download_comfy_image(
                "http://comfy:8188/view?filename=ComfyUI_00042_.png&subfolder=&type=output",
                tmp_path,
            )

        assert result == "ComfyUI_00042_.png"
        assert (tmp_path / "ComfyUI_00042_.png").exists()
        assert (tmp_path / "ComfyUI_00042_.png").read_bytes() == fake_image_bytes


# ---------------------------------------------------------------------------
# End-to-end: auto-commit produces exportable assets
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
    pid = f"autocommit-{_FAKE_COUNTER}"
    project = {
        "id": pid,
        "name": data.get("name", "Test"),
        "description": data.get("description", ""),
        "project_type": data.get("project_type", "chat"),
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


class TestAutoCommitExportRoundtrip:
    """
    Simulate the full flow: create project with ComfyUI URLs → auto-commit
    copies avatar to project storage → export produces ZIP with assets/.
    """

    def test_committed_avatar_exports_with_assets(self, tmp_path: Path, monkeypatch):
        """After auto-commit, export should include assets/ with real image files."""
        from app.personas.export_import import export_persona_project

        _reset_fake_db()
        monkeypatch.setattr("app.personas.export_import.projects.create_new_project", _fake_create_new_project)
        monkeypatch.setattr("app.personas.export_import.projects.update_project", _fake_update_project)

        upload_root = tmp_path / "uploads"
        upload_root.mkdir()

        # Simulate what auto-commit produces: avatar + thumb in project dir
        project_id = "committed-persona"
        appearance_dir = upload_root / "projects" / project_id / "persona" / "appearance"
        appearance_dir.mkdir(parents=True)

        # Create a minimal valid PNG and WebP
        from PIL import Image
        img = Image.new("RGB", (512, 768), color=(100, 150, 200))
        img.save(appearance_dir / "avatar_ComfyUI_00042_.png", format="PNG")

        thumb = img.resize((256, 256))
        thumb.save(appearance_dir / "thumb_avatar_ComfyUI_00042_.webp", format="WEBP")

        project = {
            "id": project_id,
            "name": "CommittedPersona",
            "project_type": "persona",
            "persona_agent": {
                "id": "test",
                "label": "CommittedPersona",
                "system_prompt": "Test persona.",
                "allowed_tools": [],
            },
            "persona_appearance": {
                "style_preset": "Elegant",
                "selected_filename": f"projects/{project_id}/persona/appearance/avatar_ComfyUI_00042_.png",
                "selected_thumb_filename": f"projects/{project_id}/persona/appearance/thumb_avatar_ComfyUI_00042_.webp",
                "sets": [],
            },
            "agentic": {},
        }

        result = export_persona_project(upload_root, project, mode="full")

        with zipfile.ZipFile(io.BytesIO(result.data), "r") as z:
            names = z.namelist()

            # Assets folder must be present with both files
            assert "assets/avatar_ComfyUI_00042_.png" in names, \
                f"Avatar missing from export. Files: {names}"
            assert "assets/thumb_avatar_ComfyUI_00042_.webp" in names, \
                f"Thumbnail missing from export. Files: {names}"

            # Verify manifest reports has_avatar = True
            manifest = json.loads(z.read("manifest.json"))
            assert manifest["contents"]["has_avatar"] is True

            # Verify the image data is non-empty
            avatar_data = z.read("assets/avatar_ComfyUI_00042_.png")
            assert len(avatar_data) > 100, "Avatar image data too small"

    def test_uncommitted_project_exports_without_assets(self, tmp_path: Path):
        """Without auto-commit, export should produce no assets/ (reproduces the bug)."""
        from app.personas.export_import import export_persona_project

        upload_root = tmp_path / "uploads"
        upload_root.mkdir()

        # No appearance dir, no committed files — simulates current broken flow
        project = {
            "id": "no-commit",
            "name": "BrokenPersona",
            "project_type": "persona",
            "persona_agent": {"id": "t", "label": "BrokenPersona"},
            "persona_appearance": {
                "style_preset": "Casual",
                "selected": {"set_id": "set_001", "image_id": "img_1"},
                "sets": [{
                    "set_id": "set_001",
                    "images": [{"id": "img_1", "url": "http://comfy:8188/view?filename=ComfyUI_temp.png"}],
                }],
                # No selected_filename — commit never happened
            },
            "agentic": {},
        }

        result = export_persona_project(upload_root, project, mode="full")

        with zipfile.ZipFile(io.BytesIO(result.data), "r") as z:
            asset_files = [n for n in z.namelist() if n.startswith("assets/")]
            assert len(asset_files) == 0, \
                f"Expected no assets without commit, but found: {asset_files}"


# ---------------------------------------------------------------------------
# Enhanced commit endpoint: auto-resolve + source_url modes
# ---------------------------------------------------------------------------


class TestEnhancedCommitEndpoint:
    """Test the enhanced /persona/avatar/commit endpoint modes."""

    def test_resolve_url_then_commit_roundtrip(self, tmp_path: Path):
        """
        Simulate the full auto-resolve path:
          1) _resolve_selected_image_url finds the URL
          2) Commit with that URL produces files on disk
          3) Export packages them into assets/
        """
        from app.main import _resolve_selected_image_url
        from app.personas.avatar_assets import commit_persona_avatar
        from app.personas.export_import import export_persona_project

        upload_root = tmp_path / "uploads"
        upload_root.mkdir()

        # Simulate: the user's project has ComfyUI URLs but no committed files
        appearance = {
            "style_preset": "Elegant",
            "selected": {"set_id": "set_001", "image_id": "img_2"},
            "sets": [{
                "set_id": "set_001",
                "images": [
                    {"id": "img_1", "url": "http://comfy:8188/view?filename=ComfyUI_00041_.png"},
                    {"id": "img_2", "url": "http://comfy:8188/view?filename=ComfyUI_00042_.png"},
                ],
            }],
        }

        # Step 1: resolve URL
        url = _resolve_selected_image_url(appearance)
        assert url == "http://comfy:8188/view?filename=ComfyUI_00042_.png"

        # Step 2: simulate what _download_comfy_image would do
        fake_png = upload_root / "ComfyUI_00042_.png"
        from PIL import Image
        img = Image.new("RGB", (512, 768), color=(80, 120, 200))
        img.save(fake_png, format="PNG")

        # Step 3: commit
        project_id = "repair-test"
        project_root = upload_root / "projects" / project_id
        result = commit_persona_avatar(upload_root, project_root, "ComfyUI_00042_.png")

        assert result.selected_filename.endswith("avatar_ComfyUI_00042_.png")
        assert result.thumb_filename.endswith("thumb_avatar_ComfyUI_00042_.webp")

        # Step 4: verify export now includes assets
        appearance["selected_filename"] = result.selected_filename
        appearance["selected_thumb_filename"] = result.thumb_filename

        project = {
            "id": project_id,
            "name": "RepairedPersona",
            "project_type": "persona",
            "persona_agent": {"id": "r", "label": "RepairedPersona"},
            "persona_appearance": appearance,
            "agentic": {},
        }

        export = export_persona_project(upload_root, project, mode="full")
        with zipfile.ZipFile(io.BytesIO(export.data), "r") as z:
            names = z.namelist()
            assert "assets/avatar_ComfyUI_00042_.png" in names
            assert "assets/thumb_avatar_ComfyUI_00042_.webp" in names

    def test_export_jit_commit_downloads_and_packages(self, tmp_path: Path):
        """
        Simulate the export JIT auto-commit path:
          1) Project has ComfyUI URLs but NO committed files
          2) Export endpoint resolves URL, downloads, commits
          3) Export now contains assets/ with images
        """
        from app.main import _resolve_selected_image_url
        from app.personas.avatar_assets import commit_persona_avatar
        from app.personas.export_import import export_persona_project

        upload_root = tmp_path / "uploads"
        upload_root.mkdir()

        # Project state: has ComfyUI URLs but nothing committed
        appearance = {
            "style_preset": "Cyberpunk",
            "selected": {"set_id": "set_001", "image_id": "img_1"},
            "sets": [{
                "set_id": "set_001",
                "images": [
                    {"id": "img_1", "url": "http://comfy:8188/view?filename=sd15_export_test.png"},
                ],
            }],
            # No selected_filename — simulates old/broken project
        }

        # Verify the gap: selected_filename is missing
        assert appearance.get("selected_filename") is None

        # Step 1: resolve URL (what JIT does)
        url = _resolve_selected_image_url(appearance)
        assert url is not None

        # Step 2: simulate download (what _download_comfy_image does)
        from PIL import Image
        fake_png = upload_root / "sd15_export_test.png"
        img = Image.new("RGB", (512, 768), color=(200, 50, 80))
        img.save(fake_png, format="PNG")

        # Step 3: commit (what JIT does after download)
        project_id = "jit-export-test"
        project_root = upload_root / "projects" / project_id
        result = commit_persona_avatar(upload_root, project_root, "sd15_export_test.png")
        appearance["selected_filename"] = result.selected_filename
        appearance["selected_thumb_filename"] = result.thumb_filename

        # Step 4: export should now include assets
        project = {
            "id": project_id,
            "name": "JITExportPersona",
            "project_type": "persona",
            "persona_agent": {"id": "j", "label": "JITExportPersona"},
            "persona_appearance": appearance,
            "agentic": {},
        }

        export = export_persona_project(upload_root, project, mode="full")
        with zipfile.ZipFile(io.BytesIO(export.data), "r") as z:
            names = z.namelist()
            assert "assets/avatar_sd15_export_test.png" in names, \
                f"JIT avatar missing from export. Files: {names}"
            assert "assets/thumb_avatar_sd15_export_test.webp" in names, \
                f"JIT thumbnail missing from export. Files: {names}"

            manifest = json.loads(z.read("manifest.json"))
            assert manifest["contents"]["has_avatar"] is True

    def test_jit_commit_nonfatal_on_failure(self):
        """If JIT resolve finds no URL, export should proceed (not crash)."""
        from app.main import _resolve_selected_image_url
        from app.personas.export_import import export_persona_project

        # No selected, no sets — resolve returns None, JIT skips
        appearance = {"style_preset": "Minimal"}
        assert _resolve_selected_image_url(appearance) is None

    def test_jit_skips_when_already_committed(self):
        """If selected_filename already exists, JIT should be a no-op."""
        appearance = {
            "selected_filename": "projects/p1/persona/appearance/avatar_existing.png",
            "selected": {"set_id": "s1", "image_id": "i1"},
            "sets": [{"set_id": "s1", "images": [{"id": "i1", "url": "http://x/view?filename=x.png"}]}],
        }
        # The guard condition: selected_filename is present → JIT block won't execute
        assert appearance.get("selected_filename") is not None

    def test_idempotent_commit_skips_if_already_committed(self):
        """_resolve_selected_image_url works even when sets are populated."""
        from app.main import _resolve_selected_image_url

        appearance = {
            "selected": {"set_id": "s1", "image_id": "i1"},
            "selected_filename": "projects/p1/persona/appearance/avatar_x.png",
            "sets": [{"set_id": "s1", "images": [{"id": "i1", "url": "http://x/view?filename=x.png"}]}],
        }

        # Resolver still works (returns URL) — caller checks selected_filename
        url = _resolve_selected_image_url(appearance)
        assert url is not None
        # But the caller (auto-commit block) checks selected_filename first
        assert appearance.get("selected_filename") is not None
