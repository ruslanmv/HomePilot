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

from .errors import ComfyUITimeout, ComfyUIUnavailable, ComfyUIWorkflowError


def comfyui_state(base_url: str, timeout: float = 8.0) -> str:
    """``"ok"``, ``"down"`` (nothing answers on the port) or ``"frozen"``
    (the port is open but ComfyUI does not answer in time).

    The probe used to allow 3 s in total, so a ComfyUI that was merely busy
    (e.g. building its node list) was reported as down and every avatar
    request failed with 503. Connecting stays fast; answering may take longer.
    """
    try:
        r = httpx.get(f"{base_url}/system_stats", timeout=httpx.Timeout(timeout, connect=2.0))
        return "ok" if r.status_code == 200 else "down"
    except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout):
        return "frozen"
    except Exception:
        return "down"


def comfyui_healthy(base_url: str) -> bool:
    """Synchronous health probe (used at import / config time)."""
    return comfyui_state(base_url) == "ok"


def describe_rejection(body: Any) -> str:
    """ComfyUI's reason for refusing a workflow (HTTP 400), in one line.

    The body looks like {"error": {"message": ...}, "node_errors": {node_id:
    {"class_type": ..., "errors": [{"message", "details"}]}}}."""
    if not isinstance(body, dict):
        return str(body)[:300]
    parts: List[str] = []
    err = body.get("error")
    if isinstance(err, dict) and err.get("message"):
        parts.append(str(err["message"]))
    for node_id, node in (body.get("node_errors") or {}).items():
        if not isinstance(node, dict):
            continue
        for e in node.get("errors") or []:
            msg = e.get("message", "") if isinstance(e, dict) else str(e)
            details = e.get("details", "") if isinstance(e, dict) else ""
            parts.append(f"{node.get('class_type', 'node')} #{node_id}: {msg}{f' ({details})' if details else ''}")
    return "; ".join(parts)[:600] or "ComfyUI rejected the workflow"


async def submit_prompt(base_url: str, workflow: Dict[str, Any]) -> str:
    """POST a workflow to ComfyUI and return the ``prompt_id``.

    Raises ComfyUIUnavailable only when ComfyUI cannot be reached. When it is
    running but refuses the workflow (missing model file, missing node, bad
    input) it raises ComfyUIWorkflowError with ComfyUI's own reason; that used
    to be reported as "unavailable", hiding the real problem."""
    # Connect fast (an off ComfyUI is reported in seconds), but give a busy or
    # just-started ComfyUI time to validate the workflow: with a 10 s limit the
    # job was often queued and run anyway while the user was told ComfyUI was
    # unavailable (and retries queued duplicates).
    # Model files in subfolders are listed with the host OS's separator ("a\b" on a
    # Windows-native ComfyUI); match the workflow's spelling to what this ComfyUI lists.
    try:
        from ...comfy_utils.model_paths import align_model_paths
        await asyncio.to_thread(align_model_paths, workflow, base_url.rstrip("/"))
    except Exception:
        pass
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0)) as client:
            r = await client.post(
                f"{base_url}/prompt",
                json={"prompt": workflow},
            )
    except Exception as exc:
        raise ComfyUIUnavailable(
            "Failed to submit workflow to ComfyUI"
        ) from exc
    if r.status_code >= 400:
        try:
            body: Any = r.json()
        except ValueError:
            body = r.text
        raise ComfyUIWorkflowError(f"ComfyUI rejected the workflow: {describe_rejection(body)}")
    try:
        return r.json()["prompt_id"]
    except Exception as exc:
        raise ComfyUIWorkflowError(f"Unexpected reply from ComfyUI: {r.text[:200]}") from exc


async def wait_for_images(
    base_url: str,
    prompt_id: str,
    timeout_s: int = 300,
    poll_interval_s: float = 1.0,
) -> List[Dict[str, Any]]:
    """Poll ``/history/{prompt_id}`` until images appear or timeout.

    ComfyUI history entries contain a ``status`` object with
    ``status_str`` ("success" / "error") and ``completed`` (bool).
    We use these to break out of the polling loop early when the
    workflow finishes but produces no images (e.g. missing model,
    cached empty run, or node error).
    """
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

            entry = hist[prompt_id]
            outputs = entry.get("outputs", {})
            images: list[dict[str, Any]] = []
            for node_out in outputs.values():
                images.extend(node_out.get("images", []))
            if images:
                return images

            # -- Early exit when ComfyUI marks the prompt as done ----------
            status = entry.get("status", {})
            status_str = status.get("status_str", "")
            completed = status.get("completed", False)

            if status_str == "error":
                msgs = status.get("messages", [])
                detail = msgs[-1] if msgs else "unknown error"
                raise ComfyUIWorkflowError(
                    f"ComfyUI workflow failed: {detail}"
                )

            if completed and not images:
                # Workflow finished successfully but produced no images.
                # This happens when nodes are fully cached with 0 outputs,
                # the SaveImage node is missing, or the model checkpoint
                # could not be loaded.
                raise ComfyUIWorkflowError(
                    "ComfyUI workflow completed but produced no images. "
                    "Check that the selected model checkpoint exists and "
                    "the workflow contains a SaveImage node."
                )

    raise ComfyUITimeout(
        f"ComfyUI workflow timed out after {timeout_s}s"
    )
