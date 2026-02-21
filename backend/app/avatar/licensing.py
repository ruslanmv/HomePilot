"""
Avatar Studio — license-gate enforcement.

Enterprise safety: prevents use of non-commercial models unless explicitly enabled.
"""

from __future__ import annotations

from .config import CFG


class LicenseDenied(Exception):
    """Raised when a non-commercial model is used without explicit opt-in."""


def enforce_license(commercial_ok: bool, pack_id: str) -> None:
    """Raise ``LicenseDenied`` if the pack is non-commercial and the env flag is off."""
    if commercial_ok:
        return
    if not CFG.allow_non_commercial:
        raise LicenseDenied(
            f"Pack '{pack_id}' is marked non-commercial. "
            "Set ALLOW_NON_COMMERCIAL_MODELS=true to enable."
        )
