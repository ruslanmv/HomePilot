"""Compute status routes (Wave A — Batch 6 / HP-2).

Read-only endpoints backing the plain-language compute status UX. Additive —
they expose the new ComputeProvider selection without altering any existing
generation route.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import compute_status, resolve_mode

router = APIRouter(prefix="/compute", tags=["compute"])


@router.get("/status")
async def get_status() -> dict:
    """Plain-language compute status for the client status pill."""
    return await compute_status()


@router.get("/mode")
async def get_mode() -> dict:
    from app.config import HOMEPILOT_COMPUTE_MODE
    return {"configured": HOMEPILOT_COMPUTE_MODE, "effective": await resolve_mode()}
