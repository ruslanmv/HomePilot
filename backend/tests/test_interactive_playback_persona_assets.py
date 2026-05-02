"""
Tests for resolve_persona_assets — turns a persona project id into
a portrait path + style anchors the edit-recipe renderer uses as
the source image for every scene.

Contract:
* Empty id → None.
* Non-persona project → None.
* Persona project without a committed portrait → None.
* Committed portrait with the file on disk → PersonaAssets dto
  carrying both the /files/ URL and the absolute local path.
* The returned path must be a file the renderer can hand to
  ComfyUI's LoadImage node (i.e. actually resolves on disk).
"""
from __future__ import annotations

import json
import pathlib

import pytest


@pytest.fixture
def tmp_uploads(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(uploads))
    return uploads


def _stub_projects(monkeypatch, project):
    from app import projects as projects_mod
    monkeypatch.setattr(
        projects_mod, "get_project_by_id",
        lambda pid: project if pid == (project or {}).get("id") else None,
    )


def test_resolve_none_for_empty_id(tmp_uploads, monkeypatch):
    from app.interactive.playback.persona_assets import resolve_persona_assets
    assert resolve_persona_assets("") is None
    assert resolve_persona_assets("   ") is None


def test_resolve_none_for_nonexistent_project(tmp_uploads, monkeypatch):
    from app.interactive.playback.persona_assets import resolve_persona_assets
    _stub_projects(monkeypatch, None)
    assert resolve_persona_assets("missing") is None


def test_resolve_none_for_non_persona_project(tmp_uploads, monkeypatch):
    from app.interactive.playback.persona_assets import resolve_persona_assets
    _stub_projects(monkeypatch, {
        "id": "p1", "project_type": "chat",
        "persona_appearance": {"selected_filename": "face.png"},
    })
    assert resolve_persona_assets("p1") is None


def test_resolve_none_when_no_portrait_committed(tmp_uploads, monkeypatch):
    from app.interactive.playback.persona_assets import resolve_persona_assets
    _stub_projects(monkeypatch, {
        "id": "p1", "project_type": "persona",
        "persona_appearance": {},
    })
    assert resolve_persona_assets("p1") is None


def test_resolve_returns_absolute_path_when_file_exists(tmp_uploads, monkeypatch):
    from app.interactive.playback.persona_assets import resolve_persona_assets
    portrait_name = "secretary_face.png"
    (tmp_uploads / portrait_name).write_bytes(b"fake-png")
    _stub_projects(monkeypatch, {
        "id": "p1", "project_type": "persona",
        "persona_appearance": {
            "selected_filename": portrait_name,
            "avatar_settings": {
                "character_prompt": "warm executive look",
                "outfit_prompt": "black blouse",
            },
        },
    })
    assets = resolve_persona_assets("p1")
    assert assets is not None
    assert assets.portrait_path == str(tmp_uploads / portrait_name)
    assert assets.portrait_url.endswith(f"/files/{portrait_name}")
    assert assets.character_prompt == "warm executive look"
    assert assets.outfit_prompt == "black blouse"


def test_resolve_none_when_file_missing_on_disk(tmp_uploads, monkeypatch):
    from app.interactive.playback.persona_assets import resolve_persona_assets
    _stub_projects(monkeypatch, {
        "id": "p1", "project_type": "persona",
        "persona_appearance": {"selected_filename": "not_on_disk.png"},
    })
    assert resolve_persona_assets("p1") is None


def test_resolve_falls_back_to_app_config_upload_dir_when_env_unset(tmp_path, monkeypatch):
    """Regression for the wizard-time "persona_assets_missing" storm.

    When the FastAPI process starts without UPLOAD_DIR / DATA_DIR
    exported (common in dev via ``make start``), the local-path
    resolver used to short-circuit with empty. render_adapter had
    its own fallback onto ``app.config.UPLOAD_DIR`` but
    persona_assets.py did not — so every Persona Live library render
    aborted with ``persona_assets_missing`` even though the portrait
    was actually on disk.

    This test proves the fallback now lands: both env vars are
    deliberately unset and the resolver reaches through to
    ``app.config.UPLOAD_DIR``.
    """
    uploads = tmp_path / "uploads_via_config"
    uploads.mkdir()
    portrait_name = "persona_lina.png"
    (uploads / portrait_name).write_bytes(b"fake-png")

    # Simulate a process started without the env vars exported.
    monkeypatch.delenv("UPLOAD_DIR", raising=False)
    monkeypatch.delenv("DATA_DIR", raising=False)

    # But app.config.UPLOAD_DIR points at the real directory.
    from app import config as _app_config
    monkeypatch.setattr(_app_config, "UPLOAD_DIR", str(uploads))

    from app.interactive.playback.persona_assets import resolve_persona_assets
    _stub_projects(monkeypatch, {
        "id": "p1", "project_type": "persona",
        "persona_appearance": {"selected_filename": portrait_name},
    })
    assets = resolve_persona_assets("p1")
    assert assets is not None, (
        "resolve_persona_assets must fall back to app.config.UPLOAD_DIR "
        "when UPLOAD_DIR/DATA_DIR env vars are unset — otherwise every "
        "wizard-time library render aborts with persona_assets_missing"
    )
    assert assets.portrait_path == str(uploads / portrait_name)
