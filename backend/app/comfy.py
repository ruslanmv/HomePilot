from __future__ import annotations

import json
import os
import re
import time
import uuid
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

import httpx

from .config import COMFY_BASE_URL, COMFY_POLL_INTERVAL_S, COMFY_POLL_MAX_S, UPLOAD_DIR


def _get_comfyui_input_dir() -> Path:
    """
    Find ComfyUI's input directory for uploading images.

    1. If COMFY_INPUT_DIR is set, use it
    2. Try repo paths (for local development): HomePilot/ComfyUI/input or HomePilot/comfyui/input
    3. Fallback to /comfyui/input (docker)
    """
    env_dir = os.getenv("COMFY_INPUT_DIR", "").strip()
    if env_dir:
        return Path(env_dir)

    current_file = Path(__file__).resolve()
    repo_root = current_file.parent.parent.parent  # HomePilot root

    # Try common layouts (both capitalized and lowercase)
    candidates = [
        repo_root / "ComfyUI" / "input",           # Capitalized ComfyUI
        repo_root / "comfyui" / "input",           # Lowercase comfyui
        repo_root / "comfyui" / "ComfyUI" / "input",  # Nested structure
        repo_root / "models" / "comfy" / "input",  # Alternative location
    ]

    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            print(f"[COMFY] Using input directory: {candidate}")
            return candidate

    # Try to create if ComfyUI directory exists (try both cases)
    for comfyui_name in ["ComfyUI", "comfyui"]:
        comfyui_dir = repo_root / comfyui_name
        if comfyui_dir.exists():
            input_dir = comfyui_dir / "input"
            input_dir.mkdir(parents=True, exist_ok=True)
            print(f"[COMFY] Created input directory: {input_dir}")
            return input_dir

    return Path("/comfyui/input")


def _is_url(value: str) -> bool:
    """Check if a string is a URL."""
    try:
        result = urlparse(value)
        return result.scheme in ('http', 'https')
    except Exception:
        return False


def _is_local_backend_url(url: str) -> bool:
    """
    Check if URL points to the local backend's /files/ endpoint.
    These URLs can be read directly from UPLOAD_DIR instead of HTTP.
    """
    try:
        parsed = urlparse(url)
        # Match localhost:8000, 127.0.0.1:8000, or any local backend URLs with /files/
        if parsed.path.startswith('/files/'):
            host = parsed.hostname or ''
            if host in ('localhost', '127.0.0.1', '0.0.0.0'):
                return True
        return False
    except Exception:
        return False


def _get_local_file_path(url: str) -> Path | None:
    """
    Extract the local file path from a backend /files/ URL.
    Returns None if not a valid local backend URL.
    """
    try:
        parsed = urlparse(url)
        if not parsed.path.startswith('/files/'):
            return None

        # Extract filename from /files/<filename>
        filename = parsed.path.replace('/files/', '', 1)
        if not filename:
            return None

        # Build the local path from UPLOAD_DIR
        local_path = Path(UPLOAD_DIR) / filename
        if local_path.exists():
            return local_path
        return None
    except Exception:
        return None


def _download_image_for_comfyui(image_url: str) -> str:
    """
    Download an image from a URL to ComfyUI's input directory.

    Returns the filename (not full path) to use in the workflow.
    ComfyUI's LoadImage node expects just the filename, as it looks
    in its own input directory.

    Special handling for local backend URLs:
    - If URL points to localhost:8000/files/..., read directly from UPLOAD_DIR
    - This avoids HTTP request timeout when backend requests from itself
    """
    input_dir = _get_comfyui_input_dir()
    input_dir.mkdir(parents=True, exist_ok=True)

    # Extract original filename or generate a unique one
    parsed = urlparse(image_url)
    original_filename = os.path.basename(parsed.path)

    # Ensure we have a valid extension
    if not original_filename or '.' not in original_filename:
        original_filename = f"edit_input_{uuid.uuid4().hex[:8]}.png"

    # Use a unique filename to avoid conflicts
    unique_id = uuid.uuid4().hex[:8]
    base, ext = os.path.splitext(original_filename)
    filename = f"{base}_{unique_id}{ext}"
    dest_path = input_dir / filename

    # Check if this is a local backend URL - read directly from filesystem
    if _is_local_backend_url(image_url):
        local_file = _get_local_file_path(image_url)
        if local_file and local_file.exists():
            print(f"[COMFY] Copying local file from {local_file} to {dest_path}")
            try:
                shutil.copy2(local_file, dest_path)
                print(f"[COMFY] Local file copied successfully: {filename}")
                return filename
            except Exception as e:
                print(f"[COMFY] WARNING: Failed to copy local file: {e}")
                # Fall through to HTTP download as fallback
        else:
            print(f"[COMFY] WARNING: Local file not found at {local_file}, trying HTTP download")

    print(f"[COMFY] Downloading image from {image_url} to {dest_path}")

    # Download the image via HTTP
    timeout = httpx.Timeout(30.0, connect=10.0)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(image_url)
            response.raise_for_status()

            with open(dest_path, 'wb') as f:
                f.write(response.content)

        print(f"[COMFY] Image downloaded successfully: {filename}")
        return filename
    except httpx.TimeoutException as e:
        print(f"[COMFY] WARNING: HTTP download timed out: {e}")
        raise
    except Exception as e:
        print(f"[COMFY] WARNING: HTTP download failed: {e}")
        raise


def _preprocess_image_paths(variables: Dict[str, Any]) -> Dict[str, Any]:
    """
    Preprocess variables to download any URL-based images to ComfyUI's input directory.

    ComfyUI's LoadImage node expects local filenames in its input directory,
    not HTTP URLs. This function downloads images from URLs and replaces
    the URL with the local filename.
    """
    processed = dict(variables)

    # Keys that might contain image URLs
    image_keys = ['image_path', 'image', 'input_image', 'source_image']

    for key in image_keys:
        if key in processed and isinstance(processed[key], str):
            value = processed[key]
            if _is_url(value):
                try:
                    filename = _download_image_for_comfyui(value)
                    processed[key] = filename
                    print(f"[COMFY] Replaced {key} URL with local file: {filename}")
                except Exception as e:
                    print(f"[COMFY] WARNING: Failed to download image from {value}: {e}")
                    # Keep the original value, will likely fail but provides better error

    return processed


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

    # Preprocess image paths: download URLs to ComfyUI's input directory
    # ComfyUI's LoadImage node expects local filenames, not URLs
    processed_vars = _preprocess_image_paths(variables)
    if processed_vars != variables:
        print(f"[COMFY] Processed variables: {processed_vars}")

    workflow = _load_workflow(name)
    prompt_graph = _deep_replace(workflow, processed_vars)

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
