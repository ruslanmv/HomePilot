"""
Tests for asset_urls.resolve_asset_url.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from app.interactive.playback.asset_urls import resolve_asset_url


def _install_get_asset(
    monkeypatch: pytest.MonkeyPatch,
    responses: Dict[str, Optional[Dict[str, Any]]] | Exception,
) -> None:
    import app.asset_registry as registry_mod

    def _fake(asset_id: str):
        if isinstance(responses, Exception):
            raise responses
        return responses.get(asset_id)

    monkeypatch.setattr(registry_mod, "get_asset", _fake)


def test_empty_asset_id_returns_none():
    assert resolve_asset_url("") is None


def test_stub_ids_never_resolve(monkeypatch):
    _install_get_asset(monkeypatch, {})
    assert resolve_asset_url("ixa_stub_12345") is None


def test_playback_prefix_is_stripped_before_lookup(monkeypatch):
    captured: Dict[str, Any] = {}

    import app.asset_registry as registry_mod

    def _fake(asset_id: str):
        captured["asked"] = asset_id
        return {"id": asset_id, "storage_key": "http://x/scene.mp4"}

    monkeypatch.setattr(registry_mod, "get_asset", _fake)
    url = resolve_asset_url("ixa_playback_a_real_42")
    assert url == "http://x/scene.mp4"
    assert captured["asked"] == "a_real_42"


def test_plain_asset_id_resolves(monkeypatch):
    _install_get_asset(monkeypatch, {"a_xyz": {"id": "a_xyz", "storage_key": "http://x/clip.webm"}})
    assert resolve_asset_url("a_xyz") == "http://x/clip.webm"


def test_missing_asset_returns_none(monkeypatch):
    _install_get_asset(monkeypatch, {})
    assert resolve_asset_url("a_nothing_here") is None


def test_empty_storage_key_returns_none(monkeypatch):
    _install_get_asset(monkeypatch, {"a_zero": {"id": "a_zero", "storage_key": ""}})
    assert resolve_asset_url("a_zero") is None


def test_registry_exception_returns_none(monkeypatch):
    _install_get_asset(monkeypatch, RuntimeError("db locked"))
    assert resolve_asset_url("a_xyz") is None


def test_relative_comfy_view_url_is_absolutized(monkeypatch):
    _install_get_asset(
        monkeypatch,
        {"a_xyz": {"id": "a_xyz", "storage_key": "view?filename=img_1.png&type=output"}},
    )
    import app.interactive.media_router as mr

    monkeypatch.setattr(mr, "resolve_current_comfy_base_url", lambda: "http://localhost:8188")
    assert resolve_asset_url("a_xyz") == "http://localhost:8188/view?filename=img_1.png&type=output"


def test_slash_relative_comfy_view_url_is_absolutized(monkeypatch):
    _install_get_asset(
        monkeypatch,
        {"a_xyz": {"id": "a_xyz", "storage_key": "/view?filename=img_2.png&subfolder=&type=output"}},
    )
    import app.interactive.media_router as mr

    monkeypatch.setattr(mr, "resolve_current_comfy_base_url", lambda: "http://localhost:8188")
    assert resolve_asset_url("a_xyz") == "http://localhost:8188/view?filename=img_2.png&subfolder=&type=output"
