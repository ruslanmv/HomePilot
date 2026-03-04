"""
Avatar History — Additive (non-destructive) helper utilities for avatar versioning.

- Keeps old images (never deletes)
- Tracks history inside persona_appearance["avatar_history"]
- Provides safe append + dedupe + revert

Drop-in module: does not modify existing code paths.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_avatar_history(appearance: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Ensure avatar_history list exists in appearance dict."""
    hist = appearance.get("avatar_history")
    if not isinstance(hist, list):
        hist = []
        appearance["avatar_history"] = hist
    return hist


def append_previous_avatar_if_needed(
    appearance: Dict[str, Any],
    *,
    note: str = "edited",
    replaced_by: Optional[str] = None,
) -> None:
    """
    Append the *current* selected avatar+thumb into history
    before it gets replaced.  Does nothing if no selected avatar exists.

    Non-destructive: we only record metadata; we never delete files.
    """
    current_sel = appearance.get("selected_filename")
    current_th = appearance.get("selected_thumb_filename")

    if not isinstance(current_sel, str) or not current_sel:
        return
    if not isinstance(current_th, str) or not current_th:
        return

    hist = ensure_avatar_history(appearance)

    # Dedupe: if last history item already equals current selected, skip
    if hist:
        last = hist[-1] if isinstance(hist[-1], dict) else {}
        if (
            last.get("selected_filename") == current_sel
            and last.get("selected_thumb_filename") == current_th
        ):
            return

    hist.append(
        {
            "selected_filename": current_sel,
            "selected_thumb_filename": current_th,
            "created_at": _now_iso(),
            "note": note,
            "replaced_by": replaced_by,
        }
    )


def list_avatar_history(appearance: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return a clean list of avatar history items."""
    hist = appearance.get("avatar_history")
    if isinstance(hist, list):
        return [h for h in hist if isinstance(h, dict)]
    return []


def revert_to_history_index(appearance: Dict[str, Any], index: int) -> Dict[str, Any]:
    """
    Set selected avatar to one of the historical versions.
    Keeps current selected in history (so revert is also non-destructive).
    """
    hist = list_avatar_history(appearance)
    if index < 0 or index >= len(hist):
        raise IndexError("Invalid history index")

    target = hist[index]
    sel = target.get("selected_filename")
    th = target.get("selected_thumb_filename")
    if not sel or not th:
        raise ValueError("History item missing filename")

    # Before switching, record current as previous
    append_previous_avatar_if_needed(appearance, note="revert")

    appearance["selected_filename"] = sel
    appearance["selected_thumb_filename"] = th
    appearance["avatar_history"] = hist
    return appearance
