"""
Avatar / video-clip adapter.

Two entry points:

  attach_existing_asset(node_id, asset_id, kind)
      Registers an already-generated file_assets row as an asset
      for an interactive node. Used when a designer points at an
      existing studio-generated clip or uploads a custom video.

  register_interactive_segment(node_id, user_id, rel_path, ...)
      Creates a file_assets row for a newly-produced interactive
      segment (e.g. from a future real asset generator), tags it
      with ``kind='interactive_segment'``, and wires it onto the
      node.

Both return the asset_id. Both are non-destructive — they never
touch studio tables, they only READ existing file_assets rows and
ADD new ``interactive_*``-kinded rows.
"""
from __future__ import annotations

from typing import Optional

from .. import repo
from .. import store


def attach_existing_asset(node_id: str, asset_id: str) -> str:
    """Add ``asset_id`` to the node's ``asset_ids`` list.

    Idempotent — if the id is already attached, this is a no-op.
    Returns the asset_id (for symmetry with ``register_interactive_
    segment``).
    """
    store.ensure_schema()
    node = repo.get_node(node_id)
    if node is None:
        raise ValueError(f"Node {node_id} not found")
    ids = list(node.asset_ids or [])
    if asset_id and asset_id not in ids:
        ids.append(asset_id)
        from ..models import NodeUpdate
        repo.update_node(node_id, NodeUpdate(asset_ids=ids))
    return asset_id


def register_interactive_segment(
    *,
    node_id: str,
    user_id: str,
    rel_path: str,
    mime: str = "video/mp4",
    size_bytes: int = 0,
    original_name: str = "",
    duration_sec: float = 0.0,
) -> Optional[str]:
    """Register a new interactive video segment in file_assets +
    attach it to the node. Returns the asset_id, or None if the
    files subsystem is unavailable.
    """
    try:
        from ...files import insert_asset  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        asset_id = insert_asset(
            user_id=user_id,
            kind="interactive_segment",
            rel_path=rel_path,
            mime=mime,
            size_bytes=int(size_bytes or 0),
            original_name=original_name,
        )
    except Exception:
        return None
    try:
        attach_existing_asset(node_id, asset_id)
    except Exception:
        # The asset exists in file_assets, just failed to attach to
        # the node. Return the id so the caller can retry attach.
        pass
    return asset_id
