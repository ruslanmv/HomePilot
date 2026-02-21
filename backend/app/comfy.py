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
from .comfy_utils import ComfyObjectInfoCache, remap_workflow_nodes, find_missing_class_types, NODE_ALIAS_CANDIDATES
from .model_config import get_architecture

# ---------------------------------------------------------------------------
# ComfyUI node availability cache (populated from /object_info)
# ---------------------------------------------------------------------------
_object_info_cache = ComfyObjectInfoCache(COMFY_BASE_URL, ttl_seconds=300.0)


def _fetch_object_info(force: bool = False) -> Dict[str, Any]:
    """
    Fetch ComfyUI /object_info (all registered node classes) with caching.
    Returns a dict mapping node class names to their definitions.
    """
    raw = _object_info_cache.get_raw(force=force)
    return raw or {}


def get_available_node_names(*, force: bool = False) -> list[str]:
    """Return list of node class names registered in ComfyUI."""
    return _object_info_cache.get_available_nodes(force=force)


def check_nodes_available(node_classes: list[str]) -> tuple[bool, list[str]]:
    """
    Check if the given node class names are registered in ComfyUI.

    Returns:
        (all_ok, missing_list) — True if all nodes exist, otherwise False
        with a list of missing node class names.
    """
    available = set(get_available_node_names())
    if not available:
        # Can't reach ComfyUI — let the workflow attempt proceed and fail naturally
        return True, []

    missing: list[str] = []
    for cls in node_classes:
        if cls in available:
            continue

        # Alias-aware: treat node as available if any known alias exists.
        # This keeps preflight behavior consistent with validate_workflow_nodes()
        # which already does alias remapping.
        candidates = NODE_ALIAS_CANDIDATES.get(cls, ())
        if candidates and any(alt in available for alt in candidates):
            continue

        missing.append(cls)
    return len(missing) == 0, missing


# Known node→package mapping for actionable error messages
_NODE_PACKAGE_HINTS: Dict[str, str] = {
    "InstantIDFaceAnalysis": (
        "cubiq/ComfyUI_InstantID custom nodes + insightface.\n"
        "  Fix: git clone https://github.com/cubiq/ComfyUI_InstantID.git ComfyUI/custom_nodes/ComfyUI-InstantID\n"
        "       pip install insightface onnxruntime   (in ComfyUI's Python env)\n"
        "  Then restart ComfyUI."
    ),
    "InstantIDModelLoader": (
        "cubiq/ComfyUI_InstantID custom nodes.\n"
        "  Fix: git clone https://github.com/cubiq/ComfyUI_InstantID.git ComfyUI/custom_nodes/ComfyUI-InstantID\n"
        "  Then restart ComfyUI."
    ),
    "ApplyInstantID": (
        "cubiq/ComfyUI_InstantID custom nodes.\n"
        "  Fix: git clone https://github.com/cubiq/ComfyUI_InstantID.git ComfyUI/custom_nodes/ComfyUI-InstantID\n"
        "  Then restart ComfyUI."
    ),
    "FaceDetailer": (
        "ltdrdata/ComfyUI-Impact-Pack.\n"
        "  Fix: git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git ComfyUI/custom_nodes/ComfyUI-Impact-Pack\n"
        "  Then restart ComfyUI."
    ),
    "UltralyticsDetectorProvider": (
        "ltdrdata/ComfyUI-Impact-Pack + ultralytics.\n"
        "  Fix: git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git ComfyUI/custom_nodes/ComfyUI-Impact-Pack\n"
        "       pip install ultralytics   (in ComfyUI's Python env)\n"
        "  Then restart ComfyUI."
    ),
    "FaceRestoreModelLoader": (
        "ltdrdata/ComfyUI-Impact-Pack + facexlib/gfpgan.\n"
        "  Fix: git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git ComfyUI/custom_nodes/ComfyUI-Impact-Pack\n"
        "       pip install facexlib gfpgan   (in ComfyUI's Python env)\n"
        "  Then restart ComfyUI."
    ),
    "FaceRestoreWithModel": (
        "ltdrdata/ComfyUI-Impact-Pack + facexlib/gfpgan.\n"
        "  Fix: pip install facexlib gfpgan   (in ComfyUI's Python env)\n"
        "  Then restart ComfyUI."
    ),
}


def _check_controlnet_architecture(workflow_name: str, prompt_graph: Dict[str, Any]) -> None:
    """
    Detect SDXL-only ControlNet models paired with SD1.5 checkpoints.

    The InstantID ControlNet (``diffusion_pytorch_model.safetensors``) is
    SDXL-only.  When used with an SD1.5 checkpoint, ComfyUI crashes with
    ``ValueError: y is None`` because the cross-attention dimensions don't
    match.  This guard catches the mismatch early with a clear message.
    """
    # ControlNet model filenames that are SDXL-only
    _SDXL_ONLY_CONTROLNETS = {
        "InstantID/diffusion_pytorch_model.safetensors",
        "diffusion_pytorch_model.safetensors",  # InstantID default
    }

    # Collect checkpoint and ControlNet model names from the graph
    ckpt_name = None
    controlnet_names: list[str] = []

    for _node_id, node in prompt_graph.items():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type", "")
        inputs = node.get("inputs", {})

        if ct == "CheckpointLoaderSimple":
            ckpt_name = inputs.get("ckpt_name")
        elif ct == "ControlNetLoader":
            cn = inputs.get("control_net_name")
            if cn:
                controlnet_names.append(cn)

    if not ckpt_name or not controlnet_names:
        return

    # Determine checkpoint architecture
    arch = get_architecture(ckpt_name)

    # Check for SDXL-only ControlNets with non-SDXL checkpoints
    for cn in controlnet_names:
        if cn in _SDXL_ONLY_CONTROLNETS and arch == "sd15":
            raise RuntimeError(
                f"Architecture mismatch in workflow '{workflow_name}': "
                f"ControlNet '{cn}' is SDXL-only but checkpoint "
                f"'{ckpt_name}' is SD1.5 architecture.\n\n"
                "The InstantID ControlNet requires an SDXL checkpoint. "
                "SD1.5 models cause 'y is None' errors because the cross-attention "
                "dimensions are incompatible (768 vs 2048).\n\n"
                "Fix: Use an SDXL checkpoint (e.g. sd_xl_base_1.0.safetensors) "
                "or switch to a non-identity workflow for SD1.5 models."
            )


def validate_workflow_nodes(workflow_name: str, prompt_graph: Dict[str, Any]) -> None:
    """
    Pre-flight check with automatic node alias remapping and architecture guard.

    1. Fetches the list of available nodes from ComfyUI /object_info.
    2. Runs the alias remapper — if a workflow references ``InstantIDFaceAnalysis``
       but ComfyUI only has ``InstantIDFaceEmbedder``, the graph is rewritten
       in-place (non-destructive to the JSON on disk).
    3. After remapping, any still-missing nodes trigger a RuntimeError with
       actionable install instructions.
    4. Checks for ControlNet/checkpoint architecture mismatches (e.g. SDXL
       ControlNet with SD1.5 checkpoint).
    """
    # Step 0: architecture mismatch guard (always runs, even without /object_info)
    _check_controlnet_architecture(workflow_name, prompt_graph)

    available = get_available_node_names()
    if not available:
        # Can't reach ComfyUI — let the workflow attempt proceed and fail naturally
        return

    # Step 1: try alias remapping
    replacements = remap_workflow_nodes(prompt_graph, available)
    if replacements:
        print(f"[COMFY] Node alias remap applied for '{workflow_name}': {replacements}")

    # Step 2: check for anything still missing after remapping
    missing = find_missing_class_types(prompt_graph, available)
    if not missing:
        return

    # Build a helpful error message
    parts = [
        f"ComfyUI cannot run workflow '{workflow_name}' because the following "
        f"node class(es) are not registered:\n"
    ]
    for cls in missing:
        hint = _NODE_PACKAGE_HINTS.get(cls, "Unknown package — check ComfyUI custom_nodes.")
        parts.append(f"  • {cls}  →  Requires: {hint}\n")

    parts.append(
        "\nThis usually means a custom node package is not installed or its Python "
        "dependencies failed to import (check ComfyUI startup logs for import errors).\n"
        "After installing, restart ComfyUI and verify the node appears at "
        f"{COMFY_BASE_URL}/object_info"
    )
    raise RuntimeError("".join(parts))


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

    Also handles local /files/... paths from the backend's upload directory.
    """
    processed = dict(variables)

    # Keys that might contain image URLs
    image_keys = ['image_path', 'image', 'input_image', 'source_image', 'original_image_path', 'reference_image_url']

    for key in image_keys:
        if key in processed and isinstance(processed[key], str):
            value = processed[key]

            # Handle full URLs (http://... or https://...)
            if _is_url(value):
                try:
                    filename = _download_image_for_comfyui(value)
                    processed[key] = filename
                    print(f"[COMFY] Replaced {key} URL with local file: {filename}")
                except Exception as e:
                    print(f"[COMFY] WARNING: Failed to download image from {value}: {e}")
                    # Keep the original value, will likely fail but provides better error

            # Handle local /files/... paths from backend uploads
            elif value.startswith('/files/'):
                try:
                    filename = value.replace('/files/', '', 1)
                    local_path = Path(UPLOAD_DIR) / filename
                    if local_path.exists():
                        # Copy to ComfyUI's input directory
                        input_dir = _get_comfyui_input_dir()
                        input_dir.mkdir(parents=True, exist_ok=True)
                        dest_path = input_dir / filename
                        import shutil
                        shutil.copy2(local_path, dest_path)
                        processed[key] = filename
                        print(f"[COMFY] Copied {key} to ComfyUI input: {filename}")
                    else:
                        print(f"[COMFY] WARNING: Local file not found: {local_path}")
                except Exception as e:
                    print(f"[COMFY] WARNING: Failed to copy local file {value}: {e}")

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


def _strip_meta_keys(obj: Any) -> Any:
    """Recursively strip _meta and other underscore-prefixed keys from workflow."""
    if isinstance(obj, dict):
        return {k: _strip_meta_keys(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [_strip_meta_keys(x) for x in obj]
    return obj


def _load_workflow(name: str) -> Dict[str, Any]:
    p = WORKFLOWS_DIR / f"{name}.json"
    if not p.exists():
        raise FileNotFoundError(
            f"Workflow file not found: {p}. "
            f"Set COMFY_WORKFLOWS_DIR or mount workflows into {WORKFLOWS_DIR}."
        )
    workflow = json.loads(p.read_text(encoding="utf-8"))
    # Strip metadata keys (like _meta) that ComfyUI doesn't understand
    # These are used for documentation in our workflow files
    return _strip_meta_keys(workflow)


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
    # Generate a unique client_id for each request to prevent ComfyUI caching
    # Without this, ComfyUI may skip execution for "duplicate" prompts
    import uuid
    client_id = str(uuid.uuid4())
    try:
        r = client.post(url, json={"prompt": prompt, "client_id": client_id})
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = e.response.text
        except Exception:
            pass
        # Parse error body to provide helpful suggestions
        error_msg = _parse_comfy_error(body)
        raise RuntimeError(error_msg) from e

    data = r.json()

    # Check for validation errors in response (ComfyUI may return prompt_id but fail validation)
    if "error" in data:
        error_info = data.get("error", {})
        error_type = error_info.get("type", "unknown")
        error_message = error_info.get("message", "Unknown error")

        # Check for node errors which indicate missing models
        node_errors = data.get("node_errors", {})
        if node_errors:
            error_msg = _parse_node_errors(node_errors, error_message)
            raise RuntimeError(error_msg)

        raise RuntimeError(f"ComfyUI validation failed: {error_message}")

    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not return prompt_id. Response: {data}")
    return str(prompt_id)


def _parse_comfy_error(body: str) -> str:
    """Parse ComfyUI error body and provide helpful suggestions."""
    error_msg = f"ComfyUI /prompt failed. "

    # Check for missing node classes ("does not exist")
    # This is the error ComfyUI returns when a custom node package is not installed
    # or its Python dependencies failed to import.
    if "does not exist" in body and "invalid_prompt" in body:
        # Extract the node class name from the error message
        import re
        node_match = re.search(r"node (\w+) does not exist", body)
        node_name = node_match.group(1) if node_match else "Unknown"
        hint = _NODE_PACKAGE_HINTS.get(node_name, "")
        error_msg += (
            f"\n\n[MISSING NODE] {node_name} does not exist in ComfyUI.\n"
            "This means the custom node package is not installed or its Python "
            "dependencies failed to import (check ComfyUI startup logs).\n"
        )
        if hint:
            error_msg += f"  Requires: {hint}\n"
        error_msg += (
            "\nCommon fixes:\n"
            "  Face restore: pip install facexlib gfpgan + install ComfyUI-Impact-Pack\n"
            "  InstantID: pip install insightface onnxruntime + install ComfyUI_InstantID\n"
            "Then restart ComfyUI."
        )
        return error_msg

    # Check for common missing model patterns
    if "not in list" in body.lower() or "value not in list" in body.lower():
        error_msg += "A required model file is missing. "

        # Extract model name from error
        if "t5xxl_fp8" in body.lower():
            error_msg += (
                "\n\n[MISSING MODEL] T5-XXL FP8 Text Encoder\n"
                "This encoder is required for LTX-Video on 12-16GB VRAM.\n"
                "Download from: Models > Add-ons > T5-XXL FP8 Text Encoder\n"
                "Or run: make download-minimum"
            )
        elif "t5xxl_fp16" in body.lower():
            error_msg += (
                "\n\n[MISSING MODEL] T5-XXL FP16 Text Encoder\n"
                "This encoder is required for LTX-Video on 24GB+ VRAM.\n"
                "Download from: Models > Add-ons > T5-XXL FP16 Text Encoder"
            )
        elif "ltx-video" in body.lower() or "ltx_video" in body.lower():
            error_msg += (
                "\n\n[MISSING MODEL] LTX-Video Checkpoint\n"
                "Download from: Models > Video > LTX-Video 2B\n"
                "Or run: make download-minimum"
            )
        elif "clip" in body.lower():
            error_msg += (
                "\n\n[MISSING MODEL] CLIP/Text Encoder\n"
                "Check Models > Add-ons for required encoders."
            )
        else:
            error_msg += f"\nDetails: {body[:300]}"
    else:
        error_msg += f"Response: {body[:400]}"

    return error_msg


def _parse_node_errors(node_errors: dict, base_message: str) -> str:
    """Parse node-specific errors and provide helpful suggestions."""
    error_parts = [f"ComfyUI workflow validation failed: {base_message}\n"]

    for node_id, errors in node_errors.items():
        node_type = errors.get("class_type", "Unknown")
        node_errs = errors.get("errors", [])

        for err in node_errs:
            err_type = err.get("type", "")
            err_msg = err.get("message", "")
            err_details = err.get("details", "")

            if "value_not_in_list" in err_type.lower() or "not in list" in err_msg.lower():
                # Missing model error
                if "CLIPLoader" in node_type:
                    if "t5xxl_fp8" in str(err_details).lower():
                        error_parts.append(
                            "\n[MISSING MODEL] T5-XXL FP8 Text Encoder (t5xxl_fp8_e4m3fn.safetensors)\n"
                            "Required for: LTX-Video on 12-16GB VRAM GPUs\n"
                            "Install via: Models > Add-ons > T5-XXL FP8 Text Encoder\n"
                            "Or run: make download-minimum"
                        )
                    elif "t5xxl_fp16" in str(err_details).lower():
                        error_parts.append(
                            "\n[MISSING MODEL] T5-XXL FP16 Text Encoder (t5xxl_fp16.safetensors)\n"
                            "Required for: LTX-Video on 24GB+ VRAM GPUs (Ultra preset)\n"
                            "Install via: Models > Add-ons > T5-XXL FP16 Text Encoder"
                        )
                    else:
                        error_parts.append(f"\n[MISSING MODEL] Text encoder: {err_details}")
                elif "CheckpointLoader" in node_type:
                    error_parts.append(
                        f"\n[MISSING MODEL] Checkpoint not found: {err_details}\n"
                        "Check Models section for required video/image models."
                    )
                else:
                    error_parts.append(f"\n[ERROR] Node {node_type}: {err_msg}")
            else:
                error_parts.append(f"\n[ERROR] {node_type}: {err_msg}")

    return "".join(error_parts)


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
                url = _view_url(
                    filename=str(fn),
                    subfolder=str(img.get("subfolder", "")),
                    filetype=str(img.get("type", "output")),
                )
                # Check if this is an animated format (WEBP/GIF from SaveAnimatedWEBP)
                fn_lower = str(fn).lower()
                if fn_lower.endswith('.webp') or fn_lower.endswith('.gif'):
                    videos.append(url)
                else:
                    images.append(url)

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

    # ── Pre-flight node availability check ───────────────────────
    # Query ComfyUI /object_info to verify all required node classes
    # are registered BEFORE submitting the prompt.  This turns cryptic
    # "invalid_prompt" errors into actionable install instructions.
    validate_workflow_nodes(name, prompt_graph)

    # ── Unresolved variable detection ────────────────────────────
    # Scan for any remaining {{var}} placeholders that weren't substituted.
    # These would be sent as literal strings to ComfyUI and cause validation
    # failures (e.g. "{{ckpt_name}}" is not a valid checkpoint filename).
    _unresolved_re = re.compile(r"\{\{(\w+)\}\}")
    _graph_str = json.dumps(prompt_graph)
    _unresolved = set(_unresolved_re.findall(_graph_str))
    if _unresolved:
        print(f"[COMFY] WARNING: Unresolved template variables in workflow '{name}': {_unresolved}")
        print(f"[COMFY] These variables were not provided and will be sent as literal '{{{{...}}}}' strings.")
        print(f"[COMFY] Available variables were: {list(processed_vars.keys())}")

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
