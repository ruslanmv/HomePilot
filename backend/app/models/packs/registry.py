"""
Model pack registry — lists available packs and checks install status.

Each pack is described by a JSON manifest in the ``manifests/`` directory.
A pack is considered "installed" if a marker file exists at
``models/packs/<pack_id>.installed`` (relative to the repo root).

This simple heuristic can be replaced with a richer registry later.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

MANIFEST_DIR = Path(__file__).parent / "manifests"
MARKER_DIR = Path("models") / "packs"


def list_packs() -> List[Dict[str, Any]]:
    """Return all pack manifests with ``installed`` flag populated."""
    packs: list[dict[str, Any]] = []
    for mf in sorted(MANIFEST_DIR.glob("*.json")):
        try:
            data = json.loads(mf.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        data["installed"] = _is_installed(data["id"])
        packs.append(data)
    return packs


def pack_installed(pack_id: str) -> bool:
    """Check whether a given pack is installed."""
    return _is_installed(pack_id)


def _is_installed(pack_id: str) -> bool:
    marker = MARKER_DIR / f"{pack_id}.installed"
    return marker.exists()
