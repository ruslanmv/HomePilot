"""Regression tests for ``_build_initial_scene``.

Older builds returned ``None`` when the entry node had no rendered
asset, which made ``start_session_`` hand the player a missing
``initial_scene`` field — and StandardPlayer.tsx fell through to the
"Scene not available yet." dead-end with no progress feedback. The
play route now returns a ``status="pending"`` stub instead so the
player shows "Generating scene…" and the operator can re-Play after
the background render fills in the asset_ids.

Tests use a tiny dataclass-style stand-in for the Node ORM so we
don't need to spin up a DB.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from app.interactive.routes.play import _build_initial_scene


@dataclass
class _Node:
    id: str
    title: str = ""
    narration: str = ""
    duration_sec: int = 0
    asset_ids: Sequence[str] = field(default_factory=list)


def test_pending_payload_when_no_asset_ids():
    node = _Node(id="n1", title="Opening", duration_sec=7)
    payload = _build_initial_scene(node)
    assert payload is not None
    assert payload["status"] == "pending"
    assert payload["node_id"] == "n1"
    assert payload["title"] == "Opening"
    assert payload["duration_sec"] == 7
    assert payload["asset_id"] == ""
    assert payload["asset_url"] == ""


def test_pending_payload_when_asset_ids_present_but_unresolvable():
    """A registered asset id that fails to resolve to a URL must still
    surface as pending — never as a half-built ready payload that
    would break the <img>/<video> mount in the player."""
    node = _Node(id="n2", title="Bad", asset_ids=["registry-id-with-no-row"])
    payload = _build_initial_scene(node)
    assert payload is not None
    assert payload["status"] == "pending"
    assert payload["asset_id"] == ""
    assert payload["asset_url"] == ""


def test_pending_payload_uses_default_duration_when_missing():
    node = _Node(id="n3", title="Short", duration_sec=0)
    payload = _build_initial_scene(node)
    assert payload is not None
    assert payload["duration_sec"] == 5  # the helper's default fallback


def test_ready_payload_when_asset_resolves_to_direct_path():
    # ``/files/...`` is the direct-path fallback that
    # ``_resolve_scene_asset_url`` honours when the registry has no row.
    node = _Node(id="n4", title="OK", duration_sec=4, asset_ids=["/files/scene.png"])
    payload = _build_initial_scene(node)
    assert payload is not None
    assert payload["status"] == "ready"
    assert payload["node_id"] == "n4"
    assert payload["asset_id"] == "/files/scene.png"
    assert payload["asset_url"] == "/files/scene.png"
    assert payload["media_kind"] == "image"
    assert payload["duration_sec"] == 4
