"""
Capabilities endpoint - Reports runtime feature availability.

This endpoint checks which features are actually available at runtime,
including installed models, dependencies like PIL, and ComfyUI connectivity.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict, List, Optional, Any
import importlib.util

from .edit_models import (
    get_edit_models_status,
    get_available_model,
    get_installed_models,
    ModelCategory,
)


router = APIRouter(tags=["capabilities"])


class CapabilityStatus(BaseModel):
    """Status of a single capability."""
    available: bool
    reason: Optional[str] = None
    endpoint: str
    model: Optional[str] = None
    installed_models: Optional[List[str]] = None


class CapabilitiesResponse(BaseModel):
    """Response containing all capability statuses."""
    capabilities: Dict[str, CapabilityStatus]


def _check_module(module_name: str) -> tuple[bool, Optional[str]]:
    """Check if a Python module is available."""
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return False, f"{module_name} not installed"
    return True, None


def _check_pillow() -> tuple[bool, Optional[str]]:
    """Check if PIL/Pillow is available."""
    try:
        from PIL import Image
        return True, None
    except ImportError:
        return False, "PIL/Pillow not installed"


def _check_torch_gpu() -> tuple[bool, Optional[str]]:
    """Check if PyTorch with GPU is available."""
    try:
        import torch
        if torch.cuda.is_available():
            return True, None
        return True, "CPU only (no GPU)"
    except ImportError:
        return False, "PyTorch not installed"


def _check_rembg() -> tuple[bool, Optional[str]]:
    """Check if background removal is available (rembg or ONNX fallback)."""
    # First check for rembg library
    try:
        from rembg import remove
        return True, None
    except ImportError:
        pass

    # Check for ONNX-based fallback (Python 3.11+ compatible)
    try:
        import onnxruntime
        from PIL import Image
        import numpy as np

        # Check if U2Net model is available (in ComfyUI models or user cache)
        from pathlib import Path
        from .providers import get_comfy_models_path

        # Check ComfyUI models path first
        try:
            comfy_model = get_comfy_models_path() / "rembg" / "u2net.onnx"
            if comfy_model.exists() and comfy_model.stat().st_size > 100_000_000:
                return True, "Using U2Net from ComfyUI models"
        except Exception:
            pass

        # Check user cache
        user_model = Path.home() / ".u2net" / "u2net.onnx"
        if user_model.exists() and user_model.stat().st_size > 100_000_000:
            return True, "Using ONNX Runtime (Python 3.11+ compatible)"

        # Dependencies available but model not downloaded yet
        return True, "ONNX ready (U2Net model will download on first use)"

    except ImportError:
        return False, "Background removal not available. Install onnxruntime, pooch, and scikit-image."


@router.get("/v1/capabilities", response_model=CapabilitiesResponse)
async def get_capabilities():
    """
    Get runtime capability status for all features.

    Returns availability status for each feature, including:
    - Whether the feature is available (based on installed models)
    - Reason if unavailable (missing model, dependency, etc.)
    - The API endpoint for the feature
    - The model used (if applicable)
    - List of installed models for that feature

    This allows the UI to disable unavailable features and show
    helpful error messages to users.
    """
    capabilities: Dict[str, CapabilityStatus] = {}

    # Check dependencies
    pil_ok, pil_reason = _check_pillow()

    # Get installed models for each category
    upscale_models = get_installed_models(ModelCategory.UPSCALE)
    upscale_model_ids = [m.id for m in upscale_models]
    upscale_available = len(upscale_models) > 0
    upscale_model = get_available_model(ModelCategory.UPSCALE)

    face_models = get_installed_models(ModelCategory.FACE_RESTORE)
    face_model_ids = [m.id for m in face_models]
    face_available = len(face_models) > 0
    face_model = get_available_model(ModelCategory.FACE_RESTORE)

    # Enhance photo - uses upscale models
    capabilities["enhance_photo"] = CapabilityStatus(
        available=upscale_available,
        reason=None if upscale_available else "No upscale model installed (install 4x-UltraSharp.pth or RealESRGAN_x4plus.pth)",
        endpoint="/v1/enhance",
        model=upscale_model.name if upscale_model else None,
        installed_models=upscale_model_ids,
    )

    # Enhance restore - uses upscale models
    capabilities["enhance_restore"] = CapabilityStatus(
        available=upscale_available,
        reason=None if upscale_available else "No upscale model installed (install SwinIR_4x.pth or 4x-UltraSharp.pth)",
        endpoint="/v1/enhance",
        model=upscale_model.name if upscale_model else None,
        installed_models=upscale_model_ids,
    )

    # Enhance faces - uses face restore models
    capabilities["enhance_faces"] = CapabilityStatus(
        available=face_available,
        reason=None if face_available else "No face restoration model installed (install GFPGANv1.4.pth)",
        endpoint="/v1/enhance",
        model=face_model.name if face_model else None,
        installed_models=face_model_ids,
    )

    # Upscale capability
    capabilities["upscale"] = CapabilityStatus(
        available=upscale_available,
        reason=None if upscale_available else "No upscale model installed (install 4x-UltraSharp.pth)",
        endpoint="/v1/upscale",
        model=upscale_model.name if upscale_model else None,
        installed_models=upscale_model_ids,
    )

    # Background remove - requires rembg or ComfyUI-rembg custom node
    rembg_ok, rembg_reason = _check_rembg()
    capabilities["background_remove"] = CapabilityStatus(
        available=rembg_ok,
        reason=rembg_reason,
        endpoint="/v1/background",
        model="rembg/U2Net" if rembg_ok else None,
    )

    capabilities["background_replace"] = CapabilityStatus(
        available=True,  # ComfyUI handles this
        endpoint="/v1/background",
        model="SD Inpainting",
    )

    capabilities["background_blur"] = CapabilityStatus(
        available=pil_ok,
        reason=pil_reason,
        endpoint="/v1/background",
        model="PIL GaussianBlur",
    )

    # Outpaint capability
    capabilities["outpaint"] = CapabilityStatus(
        available=True,  # ComfyUI handles this
        endpoint="/v1/outpaint",
        model="SD Outpainting",
    )

    # Inpaint capability
    capabilities["inpaint"] = CapabilityStatus(
        available=True,  # ComfyUI handles this
        endpoint="/v1/edit",
        model="SD Inpainting",
    )

    return CapabilitiesResponse(capabilities=capabilities)


@router.get("/v1/capabilities/{feature}")
async def get_capability(feature: str):
    """
    Get capability status for a specific feature.

    Valid features:
    - enhance_photo, enhance_restore, enhance_faces
    - upscale
    - background_remove, background_replace, background_blur
    - outpaint, inpaint
    """
    all_caps = await get_capabilities()

    if feature not in all_caps.capabilities:
        return {"error": f"Unknown feature: {feature}", "valid_features": list(all_caps.capabilities.keys())}

    return all_caps.capabilities[feature]


@router.get("/v1/edit-models")
async def get_edit_models():
    """
    Get comprehensive status of all edit models.

    Returns:
    - Lists of installed/available models by category
    - Currently selected models for each mode
    - Default models

    Use this to populate the settings UI for model selection.
    """
    from .edit_models import get_edit_models_status
    return get_edit_models_status()


@router.get("/v1/avatar-models")
async def get_avatar_models():
    """
    Get Avatar Generator model registry status (additive, read-only).

    Returns installed/available status for avatar generation models.
    Use this in the PersonaWizard to:
      - show which avatar generation modes are available
      - grey-out unavailable options when models are missing
      - provide download URLs and license info to the user
    """
    from .edit_models import get_avatar_models_status
    return get_avatar_models_status()



# ---------------------------------------------------------------------------
# Avatar model download — with real-time logging + background progress
# ---------------------------------------------------------------------------

import logging
import threading
import time as _time
from typing import Dict as _Dict

_avatar_dl_logger = logging.getLogger("homepilot.avatar_download")

# Shared progress state — polled by GET /v1/avatar-models/download/status
_avatar_download_state: _Dict[str, Any] = {
    "running": False,
    "preset": None,
    "started_at": None,
    "current_model": None,
    "current_index": 0,
    "total_models": 0,
    "results": [],
    "finished": False,
    "error": None,
}
_avatar_download_lock = threading.Lock()


def _fmt_bytes(n: int) -> str:
    """Human-readable byte size."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


def _download_one_model(model_id: str, model_name: str, url: str, dest_path, timeout: int = 600) -> dict:
    """
    Download a single model with real-time progress logging.
    Returns a result dict with status + details.
    """
    import subprocess
    from pathlib import Path

    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    _avatar_dl_logger.info(
        "=" * 60 + "\n"
        f"  DOWNLOAD START: {model_name}\n"
        f"  ID:   {model_id}\n"
        f"  URL:  {url}\n"
        f"  Dest: {dest}\n"
        + "=" * 60
    )

    start = _time.time()

    try:
        # Use wget with --progress=dot:mega so each dot = 1 MB received.
        # Stream stderr line-by-line to the logger.
        proc = subprocess.Popen(
            ["wget", "-c", "--progress=dot:mega", "-O", str(dest), url],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        last_log = start
        stderr_lines = []

        # Read stderr in real-time (wget sends progress to stderr)
        for line in iter(proc.stderr.readline, ""):
            line = line.rstrip()
            if not line:
                continue
            stderr_lines.append(line)

            now = _time.time()
            # Log progress lines at most every 3 seconds to avoid spam
            if "%" in line or "saved" in line.lower() or "error" in line.lower() or "failed" in line.lower():
                if now - last_log >= 3 or "100%" in line or "saved" in line.lower():
                    _avatar_dl_logger.info(f"  [{model_id}] {line}")
                    last_log = now
            elif "resolving" in line.lower() or "connecting" in line.lower() or "http request" in line.lower():
                _avatar_dl_logger.info(f"  [{model_id}] {line}")

        proc.wait(timeout=timeout)
        elapsed = _time.time() - start

        if proc.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
            file_size = dest.stat().st_size
            speed = file_size / elapsed if elapsed > 0 else 0
            _avatar_dl_logger.info(
                f"  [{model_id}] COMPLETE — {_fmt_bytes(file_size)} in {elapsed:.1f}s "
                f"({_fmt_bytes(int(speed))}/s)"
            )

            # Special case: unzip AntelopeV2 archive
            if model_id == "insightface-antelopev2" and dest.suffix == ".zip":
                _avatar_dl_logger.info(f"  [{model_id}] Extracting ZIP archive...")
                unzip = subprocess.run(
                    ["unzip", "-qo", str(dest), "-d", str(dest.parent)],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if unzip.returncode == 0:
                    _avatar_dl_logger.info(f"  [{model_id}] ZIP extracted successfully")
                else:
                    _avatar_dl_logger.warning(
                        f"  [{model_id}] ZIP extraction warning: {unzip.stderr[-200:] if unzip.stderr else 'unknown'}"
                    )

            return {"id": model_id, "name": model_name, "status": "installed", "size": file_size, "elapsed": round(elapsed, 1)}
        else:
            stderr_tail = "\n".join(stderr_lines[-5:]) if stderr_lines else "no output"
            _avatar_dl_logger.error(
                f"  [{model_id}] FAILED (exit code {proc.returncode}, {elapsed:.1f}s)\n"
                f"  Last output:\n{stderr_tail}"
            )
            return {
                "id": model_id, "name": model_name, "status": "failed",
                "error": stderr_tail[-300:] if stderr_tail else "download failed",
            }

    except subprocess.TimeoutExpired:
        proc.kill()
        _avatar_dl_logger.error(f"  [{model_id}] TIMEOUT after {timeout}s")
        return {"id": model_id, "name": model_name, "status": "timeout"}
    except FileNotFoundError:
        _avatar_dl_logger.error(f"  [{model_id}] wget not found — install wget to enable downloads")
        return {"id": model_id, "name": model_name, "status": "error", "error": "wget not found"}
    except Exception as e:
        _avatar_dl_logger.error(f"  [{model_id}] ERROR: {e}")
        return {"id": model_id, "name": model_name, "status": "error", "error": str(e)}


def _run_download_batch(preset: str, target_ids: list, all_models: dict):
    """Background thread: downloads models sequentially with full logging."""
    global _avatar_download_state

    _avatar_dl_logger.info(
        "\n" + "#" * 60 + "\n"
        f"#  AVATAR MODEL DOWNLOAD — {preset.upper()} PRESET\n"
        f"#  Models to process: {len(target_ids)}\n"
        f"#  IDs: {', '.join(target_ids)}\n"
        + "#" * 60
    )

    results = []
    for i, mid in enumerate(target_ids):
        m = all_models.get(mid)

        with _avatar_download_lock:
            _avatar_download_state["current_model"] = mid
            _avatar_download_state["current_index"] = i + 1

        if not m:
            _avatar_dl_logger.warning(f"  [{mid}] SKIP — not registered in model registry")
            results.append({"id": mid, "status": "not_registered"})
            continue

        if m.installed:
            _avatar_dl_logger.info(f"  [{mid}] SKIP — already installed at {m.path}")
            results.append({"id": mid, "name": m.name, "status": "already_installed"})
            continue

        if not m.download_url:
            _avatar_dl_logger.warning(f"  [{mid}] SKIP — no download URL configured")
            results.append({"id": mid, "name": m.name, "status": "no_download_url"})
            continue

        _avatar_dl_logger.info(f"\n  >>> Model {i + 1}/{len(target_ids)}: {m.name}")

        result = _download_one_model(mid, m.name, m.download_url, m.path)
        results.append(result)

        with _avatar_download_lock:
            _avatar_download_state["results"] = list(results)

    # Summary
    installed = sum(1 for r in results if r.get("status") in ("installed", "already_installed"))
    new_count = sum(1 for r in results if r.get("status") == "installed")
    already = sum(1 for r in results if r.get("status") == "already_installed")
    failed = sum(1 for r in results if r.get("status") not in ("installed", "already_installed"))
    total_bytes = sum(r.get("size", 0) for r in results if r.get("size"))

    _avatar_dl_logger.info(
        "\n" + "#" * 60 + "\n"
        f"#  DOWNLOAD COMPLETE — {preset.upper()} PRESET\n"
        f"#  Newly installed: {new_count}\n"
        f"#  Already present: {already}\n"
        f"#  Failed/skipped:  {failed}\n"
        f"#  Total downloaded: {_fmt_bytes(total_bytes)}\n"
        f"#  Result: {installed}/{len(target_ids)} ready\n"
        + "#" * 60
    )

    with _avatar_download_lock:
        _avatar_download_state["results"] = results
        _avatar_download_state["finished"] = True
        _avatar_download_state["running"] = False
        _avatar_download_state["current_model"] = None


AVATAR_BASIC_IDS = [
    "insightface-antelopev2",
    "instantid-ip-adapter",
    "instantid-controlnet",
]
AVATAR_FULL_IDS = AVATAR_BASIC_IDS + [
    "photomaker-v2",
    "pulid-flux",
    "insightface-inswapper-128",
    "ip-adapter-faceid-plusv2",
    "stylegan2-ffhq-256",
    "stylegan2-ffhq-1024",
]


@router.post("/v1/avatar-models/download")
async def download_avatar_models(preset: str = "basic"):
    """
    Download avatar models by preset (basic or full).

    Starts download in a background thread so the endpoint returns immediately.
    Poll GET /v1/avatar-models/download/status for progress.

    Presets:
      basic  — InsightFace AntelopeV2 + InstantID (~4.3 GB)
      full   — basic + PhotoMaker + PuLID + InSwapper + FaceID + StyleGAN2 (~9.5 GB)
    """
    global _avatar_download_state

    if preset not in ("basic", "full"):
        return {"ok": False, "error": f"Unknown preset: {preset}. Use 'basic' or 'full'."}

    # Prevent concurrent downloads
    with _avatar_download_lock:
        if _avatar_download_state["running"]:
            return {
                "ok": False,
                "error": "A download is already in progress. Check /v1/avatar-models/download/status",
                "status": _avatar_download_state,
            }

    from .edit_models import get_all_models, ModelCategory

    all_models = {m.id: m for m in get_all_models(ModelCategory.AVATAR_GENERATION)}
    target_ids = AVATAR_FULL_IDS if preset == "full" else AVATAR_BASIC_IDS

    # Reset state
    with _avatar_download_lock:
        _avatar_download_state = {
            "running": True,
            "preset": preset,
            "started_at": _time.time(),
            "current_model": None,
            "current_index": 0,
            "total_models": len(target_ids),
            "results": [],
            "finished": False,
            "error": None,
        }

    # Launch in background thread
    thread = threading.Thread(
        target=_run_download_batch,
        args=(preset, target_ids, all_models),
        daemon=True,
        name=f"avatar-dl-{preset}",
    )
    thread.start()

    _avatar_dl_logger.info(f"Download thread started for '{preset}' preset ({len(target_ids)} models)")

    return {
        "ok": True,
        "message": f"Download started for {preset} preset ({len(target_ids)} models). Poll /v1/avatar-models/download/status for progress.",
        "preset": preset,
        "total_models": len(target_ids),
        "model_ids": target_ids,
    }


@router.get("/v1/avatar-models/download/status")
async def get_avatar_download_status():
    """
    Poll download progress. Returns current state of the background download.

    Fields:
      running       — True while download thread is active
      preset        — 'basic' or 'full'
      current_model — ID of model currently downloading (null when idle)
      current_index — 1-based index of current model
      total_models  — total models in this preset
      results       — per-model results so far
      finished      — True when all models processed
      elapsed       — seconds since download started
    """
    with _avatar_download_lock:
        state = dict(_avatar_download_state)

    # Add elapsed time
    if state.get("started_at"):
        state["elapsed"] = round(_time.time() - state["started_at"], 1)
    else:
        state["elapsed"] = 0

    # Compute summary counts
    results = state.get("results", [])
    state["installed_count"] = sum(1 for r in results if r.get("status") in ("installed", "already_installed"))
    state["failed_count"] = sum(1 for r in results if r.get("status") not in ("installed", "already_installed", None))
    state["downloaded_bytes"] = sum(r.get("size", 0) for r in results if r.get("size"))

    return state


@router.delete("/v1/avatar-models/{model_id}")
async def delete_avatar_model(model_id: str):
    """
    Delete (uninstall) a single avatar model to free disk space.

    Only deletes files in the ComfyUI models directory.
    Safe and reversible — re-download at any time via the preset buttons.
    """
    import shutil

    from .edit_models import get_all_models, ModelCategory

    all_models = {m.id: m for m in get_all_models(ModelCategory.AVATAR_GENERATION)}
    m = all_models.get(model_id)

    if not m:
        return {"ok": False, "error": f"Unknown avatar model: {model_id}"}

    if not m.installed:
        return {"ok": False, "error": f"{m.name} is not installed"}

    dest = m.path
    deleted_files = []
    freed_bytes = 0

    try:
        if dest.is_file():
            size = dest.stat().st_size
            dest.unlink()
            deleted_files.append(str(dest))
            freed_bytes += size
            _avatar_dl_logger.info(f"Deleted avatar model file: {dest} ({_fmt_bytes(size)})")

        # For AntelopeV2 — also remove the extracted directory
        if model_id == "insightface-antelopev2":
            extracted_dir = dest.parent / "antelopev2"
            if extracted_dir.is_dir():
                dir_size = sum(f.stat().st_size for f in extracted_dir.rglob("*") if f.is_file())
                shutil.rmtree(extracted_dir)
                deleted_files.append(str(extracted_dir))
                freed_bytes += dir_size
                _avatar_dl_logger.info(
                    f"Deleted extracted directory: {extracted_dir} ({_fmt_bytes(dir_size)})"
                )

        _avatar_dl_logger.info(
            f"Uninstalled {m.name} — freed {_fmt_bytes(freed_bytes)}"
        )

        return {
            "ok": True,
            "model_id": model_id,
            "name": m.name,
            "deleted_files": deleted_files,
            "freed_bytes": freed_bytes,
            "freed_human": _fmt_bytes(freed_bytes),
        }

    except Exception as e:
        _avatar_dl_logger.error(f"Failed to delete {model_id}: {e}")
        return {"ok": False, "error": str(e)}


@router.post("/v1/edit-models/preference")
async def set_edit_model_preference(mode: str, model_id: str):
    """
    Set the preferred model for an edit mode.

    Args:
        mode: "upscale", "photo", "restore", or "faces"
        model_id: The model ID to use (e.g., "4x-UltraSharp", "GFPGANv1.4")

    Returns:
        Success status and any error message
    """
    from .edit_models import set_model_preference
    success, error = set_model_preference(mode, model_id)

    if success:
        return {"success": True, "mode": mode, "model": model_id}
    else:
        return {"success": False, "error": error}
