"""
ComfyUI HTTP client — submit workflows and poll for results.

Uses httpx (already a project dependency) for async-friendly HTTP.
This is a *new* reusable wrapper that complements the existing ``comfy.py``
without modifying it.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import httpx

from .errors import ComfyUITimeout, ComfyUIUnavailable


def comfyui_healthy(base_url: str) -> bool:
    """Synchronous health probe (used at import / config time)."""
    try:
        r = httpx.get(f"{base_url}/system_stats", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


async def submit_prompt(base_url: str, workflow: Dict[str, Any]) -> str:
    """POST a workflow to ComfyUI and return the ``prompt_id``."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{base_url}/prompt",
                json={"prompt": workflow},
            )
            r.raise_for_status()
            return r.json()["prompt_id"]
    except Exception as exc:
        raise ComfyUIUnavailable(
            "Failed to submit workflow to ComfyUI"
        ) from exc


async def wait_for_images(
    base_url: str,
    prompt_id: str,
    timeout_s: int = 600,
    poll_interval_s: float = 1.0,
) -> List[Dict[str, Any]]:
    """Poll ``/history/{prompt_id}`` until images appear or timeout."""
    elapsed = 0.0
    async with httpx.AsyncClient(timeout=10) as client:
        while elapsed < timeout_s:
            await asyncio.sleep(poll_interval_s)
            elapsed += poll_interval_s

            try:
                r = await client.get(f"{base_url}/history/{prompt_id}")
                hist = r.json()
            except Exception:
                continue

            if prompt_id not in hist:
                continue

            outputs = hist[prompt_id].get("outputs", {})
            images: list[dict[str, Any]] = []
            for node_out in outputs.values():
                images.extend(node_out.get("images", []))
            if images:
                return images

    raise ComfyUITimeout("ComfyUI workflow timed out")
