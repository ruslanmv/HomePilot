from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx

from .config import COMFY_BASE_URL, COMFY_POLL_INTERVAL_S, COMFY_POLL_MAX_S


def _get_workflows_dir() -> Path:
    """
    Find workflows directory intelligently:
    1. If COMFY_WORKFLOWS_DIR is set, use it
    2. Try repo path (for local development)
    3. Fallback to /workflows (docker)
    """
    env_dir = os.getenv("COMFY_WORKFLOWS_DIR", "").strip()
    if env_dir:
        return Path(env_dir)

    current_file = Path(__file__).resolve()
    repo_root = current_file.parent.parent.parent  # HomePilot root
    repo_workflows = repo_root / "comfyui" / "workflows"
    if repo_workflows.exists() and repo_workflows.is_dir():
        return repo_workflows

    return Path("/workflows")


WORKFLOWS_DIR = _get_workflows_dir()


def _deep_replace(obj: Any, mapping: Dict[str, Any]) -> Any:
    """
    Recursively replace {{key}} placeholders in workflow with variable values.

    Handles type conversion:
    - If the entire string is a placeholder like "{{width}}", replace with the actual value (preserving type)
    - If the placeholder is embedded in a string like "image_{{seed}}.png", do string replacement
    - Numeric strings are converted to int/float as needed by ComfyUI
    """
    if isinstance(obj, dict):
        return {k: _deep_replace(v, mapping) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_replace(x, mapping) for x in obj]
    if isinstance(obj, str):
        # Check if the entire string is a single placeholder (e.g., "{{width}}")
        # In this case, return the value directly to preserve its type
        stripped = obj.strip()
        for k, v in mapping.items():
            placeholder = f"{{{{{k}}}}}"
            if stripped == placeholder:
                # Return value directly, preserving type (int, float, etc.)
                return v

        # Otherwise do string replacement for embedded placeholders
        out = obj
        for k, v in mapping.items():
            out = out.replace(f"{{{{{k}}}}}", str(v))

        # If the result looks like a number and was a pure placeholder replacement,
        # try to convert it (handles cases where workflow has "{{width}}" quoted)
        if out != obj:  # Something was replaced
            # Try to convert pure numeric strings to their proper types
            try:
                if '.' in out:
                    return float(out)
                return int(out)
            except ValueError:
                pass  # Not a number, return as string

        return out
    return obj


def _load_workflow(name: str) -> Dict[str, Any]:
    p = WORKFLOWS_DIR / f"{name}.json"
    if not p.exists():
        raise FileNotFoundError(
            f"Workflow file not found: {p}. "
            f"Set COMFY_WORKFLOWS_DIR or mount workflows into {WORKFLOWS_DIR}."
        )
    return json.loads(p.read_text(encoding="utf-8"))


def _validate_prompt_graph(prompt_graph: Dict[str, Any], *, workflow_name: str) -> None:
    """
    ComfyUI /prompt expects an API-format graph:
      { "1": {"class_type": "...", "inputs": {...}}, "2": {...}, ... }
    Your repo currently ships TEMPLATE files with keys like "_comment"/"_instructions".
    Those cause ComfyUI to reply 400.
    """
    if not isinstance(prompt_graph, dict) or not prompt_graph:
        raise ValueError(
            f"Comfy workflow '{workflow_name}' is empty/invalid. "
            "Export a real ComfyUI workflow in 'API format' and replace the template JSON."
        )

    # If it looks like a template, fail early with a clear message
    template_keys = [k for k in prompt_graph.keys() if isinstance(k, str) and k.startswith("_")]
    if template_keys and all(k.startswith("_") for k in prompt_graph.keys()):
        raise ValueError(
            f"Comfy workflow '{workflow_name}' is still a TEMPLATE (contains only _comment/_instructions). "
            "You must export a real ComfyUI workflow using 'Save (API Format)' and overwrite this file:\n"
            f"  {WORKFLOWS_DIR / (workflow_name + '.json')}\n"
        )

    # Ensure at least one node has class_type
    has_node = False
    for _, node in prompt_graph.items():
        if isinstance(node, dict) and node.get("class_type"):
            has_node = True
            break
    if not has_node:
        raise ValueError(
            f"Comfy workflow '{workflow_name}' does not look like ComfyUI API format (no class_type nodes). "
            "Export from ComfyUI: Settings → enable Dev mode → Save (API Format)."
        )


def _post_prompt(client: httpx.Client, prompt: Dict[str, Any]) -> str:
    url = f"{COMFY_BASE_URL.rstrip('/')}/prompt"
    try:
        r = client.post(url, json={"prompt": prompt})
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = e.response.text
        except Exception:
            pass
        raise RuntimeError(
            f"ComfyUI /prompt failed ({e.response.status_code}). "
            f"Most common cause: workflow JSON is not API format. "
            f"Response: {body[:400]}"
        ) from e

    data = r.json()
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not return prompt_id. Response: {data}")
    return str(prompt_id)


def _get_history(client: httpx.Client, prompt_id: str) -> Dict[str, Any]:
    url = f"{COMFY_BASE_URL.rstrip('/')}/history/{prompt_id}"
    r = client.get(url)
    r.raise_for_status()
    return r.json()


def _view_url(filename: str, subfolder: str = "", filetype: str = "output") -> str:
    base = COMFY_BASE_URL.rstrip("/")
    return f"{base}/view?filename={filename}&subfolder={subfolder}&type={filetype}"


def _extract_media(history: Dict[str, Any], prompt_id: str) -> Tuple[List[str], List[str]]:
    images: List[str] = []
    videos: List[str] = []

    entry = history.get(prompt_id)
    if not isinstance(entry, dict):
        return images, videos

    outputs = entry.get("outputs") or {}
    if not isinstance(outputs, dict):
        return images, videos

    for _node_id, node_out in outputs.items():
        if not isinstance(node_out, dict):
            continue

        for img in (node_out.get("images") or []):
            if not isinstance(img, dict):
                continue
            fn = img.get("filename")
            if fn:
                images.append(
                    _view_url(
                        filename=str(fn),
                        subfolder=str(img.get("subfolder", "")),
                        filetype=str(img.get("type", "output")),
                    )
                )

        for vid in (node_out.get("gifs") or []):
            if not isinstance(vid, dict):
                continue
            fn = vid.get("filename")
            if fn:
                videos.append(
                    _view_url(
                        filename=str(fn),
                        subfolder=str(vid.get("subfolder", "")),
                        filetype=str(vid.get("type", "output")),
                    )
                )

        for vid in (node_out.get("videos") or []):
            if not isinstance(vid, dict):
                continue
            fn = vid.get("filename")
            if fn:
                videos.append(
                    _view_url(
                        filename=str(fn),
                        subfolder=str(vid.get("subfolder", "")),
                        filetype=str(vid.get("type", "output")),
                    )
                )

    return images, videos


def run_workflow(name: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    print(f"[COMFY] Running workflow: {name}")
    print(f"[COMFY] Variables: {variables}")

    workflow = _load_workflow(name)
    prompt_graph = _deep_replace(workflow, variables)

    # Log checkpoint being used (if present in workflow)
    for node_id, node in prompt_graph.items():
        if isinstance(node, dict) and node.get("class_type") == "CheckpointLoaderSimple":
            ckpt = node.get("inputs", {}).get("ckpt_name", "unknown")
            print(f"[COMFY] Checkpoint in workflow: {ckpt}")
            break

    _validate_prompt_graph(prompt_graph, workflow_name=name)

    timeout = httpx.Timeout(60.0, connect=60.0)
    with httpx.Client(timeout=timeout) as client:
        prompt_id = _post_prompt(client, prompt_graph)
        print(f"[COMFY] Prompt queued with ID: {prompt_id}")

        started = time.time()
        while True:
            history = _get_history(client, prompt_id)

            entry = history.get(prompt_id)
            if isinstance(entry, dict):
                # Check if job completed (has outputs key, even if empty)
                # Also check status.completed for newer ComfyUI versions
                status = entry.get("status", {})
                status_completed = status.get("completed", False) if isinstance(status, dict) else False
                has_outputs = "outputs" in entry

                if has_outputs or status_completed:
                    images, videos = _extract_media(history, prompt_id)
                    elapsed = time.time() - started
                    print(f"[COMFY] Workflow completed in {elapsed:.1f}s, images: {len(images)}, videos: {len(videos)}")

                    # If no images were generated, log a warning
                    if not images and not videos:
                        print(f"[COMFY] WARNING: Workflow completed but produced no output!")
                        # Check for execution errors in status
                        if isinstance(status, dict) and status.get("status_str") == "error":
                            print(f"[COMFY] Error details: {status}")

                    return {"images": images, "videos": videos, "prompt_id": prompt_id}

            if (time.time() - started) > float(COMFY_POLL_MAX_S):
                raise TimeoutError(
                    f"ComfyUI workflow '{name}' timed out after {COMFY_POLL_MAX_S}s (prompt_id={prompt_id})"
                )

            time.sleep(float(COMFY_POLL_INTERVAL_S))
