"""
LoRA API Routes — Additive REST endpoints for LoRA management.

Golden Rule 1.0: purely additive, no changes to existing routes.

Endpoints:
  GET    /v1/lora/registry          — List available LoRAs from the curated catalog
  GET    /v1/lora/installed         — List locally installed LoRA files
  POST   /v1/lora/{lora_id}/install — Download & install a LoRA from the registry
  DELETE /v1/lora/{lora_id}         — Delete an installed LoRA file
  GET    /v1/lora/download/status   — Poll download progress
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time as _time
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Query

from .lora_registry import get_lora_registry, get_lora_by_id
from .lora_loader import (
    scan_installed_loras,
    get_lora_dir,
    is_lora_compatible,
    LORA_COMPAT,
    ARCH_LABELS,
    LORA_BASE_LABELS,
)
from ..model_config import get_architecture, detect_architecture_from_filename, MODEL_ARCHITECTURES

router = APIRouter(prefix="/v1/lora", tags=["lora"])

_logger = logging.getLogger("homepilot.lora")

# ---------------------------------------------------------------------------
# Shared download state — same pattern as avatar download in capabilities.py
# ---------------------------------------------------------------------------
_lora_download_state: Dict[str, Any] = {
    "running": False,
    "started_at": None,
    "current_model": None,
    "current_index": 0,
    "total_models": 0,
    "results": [],
    "finished": False,
    "error": None,
}
_lora_download_lock = threading.Lock()


def _fmt_bytes(n: int) -> str:
    """Human-readable byte size."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


# ---------------------------------------------------------------------------
# Registry & Installed endpoints
# ---------------------------------------------------------------------------

@router.get("/registry")
async def list_lora_registry(spicy: bool = Query(False)):
    """Return the curated LoRA catalog.

    Query params:
        spicy: include gated/NSFW entries (default False)
    """
    return {
        "ok": True,
        "loras": get_lora_registry(spicy_enabled=spicy),
    }


@router.get("/installed")
async def list_installed_loras():
    """Return LoRA files found in the local models/loras directory.

    Each entry now includes `base` and `base_label` metadata from the registry.
    """
    return {
        "ok": True,
        "loras": scan_installed_loras(),
    }


@router.get("/compatibility")
async def check_lora_compatibility(checkpoint: str = Query("", description="Checkpoint filename")):
    """Check LoRA compatibility against the current checkpoint model.

    Returns each installed LoRA annotated with:
      - compatible: true/false/null (null = unknown base)
      - checkpoint_arch: detected architecture of the checkpoint
      - checkpoint_arch_label: human-readable architecture label

    Query params:
        checkpoint: checkpoint filename (e.g. "sd_xl_base_1.0.safetensors")
    """
    # Detect checkpoint architecture
    if checkpoint:
        if checkpoint in MODEL_ARCHITECTURES:
            arch = MODEL_ARCHITECTURES[checkpoint]
        else:
            arch = detect_architecture_from_filename(checkpoint)
    else:
        arch = ""

    arch_label = ARCH_LABELS.get(arch, arch.upper() if arch else "")

    installed = scan_installed_loras()

    annotated = []
    for lora in installed:
        lora_base = lora.get("base", "")
        compat = is_lora_compatible(lora_base, arch)
        annotated.append({
            **lora,
            "compatible": compat,
        })

    return {
        "ok": True,
        "checkpoint": checkpoint,
        "checkpoint_arch": arch,
        "checkpoint_arch_label": arch_label,
        "loras": annotated,
    }


# ---------------------------------------------------------------------------
# Install (download) a LoRA — background thread + polling
# ---------------------------------------------------------------------------

def _cleanup_empty_file(dest: Path, lora_id: str) -> None:
    """Remove 0-byte ghost files left by wget after a failed download."""
    try:
        if dest.exists() and dest.stat().st_size == 0:
            dest.unlink()
            _logger.info(f"  [{lora_id}] Cleaned up 0-byte file: {dest}")
    except OSError:
        pass


def _download_lora_file(lora_id: str, name: str, url: str, dest: Path, timeout: int = 600, api_key: str = "") -> dict:
    """Download a single LoRA file with wget (mirrors _download_one_model from capabilities)."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    _logger.info(
        "=" * 60 + "\n"
        f"  LORA DOWNLOAD START: {name}\n"
        f"  ID:   {lora_id}\n"
        f"  URL:  {url}\n"
        f"  Dest: {dest}\n"
        f"  Auth: {'yes' if api_key else 'no'}\n"
        + "=" * 60
    )

    start = _time.time()

    try:
        # For CivitAI: append API key as ?token= query param (not header),
        # and skip -c (resume) since Range headers break pre-signed CDN URLs.
        download_url = url
        if api_key and "civitai.com" in url:
            sep = "&" if "?" in url else "?"
            download_url = f"{url}{sep}token={api_key}"
        use_resume = "civitai.com" not in url  # Resume breaks signed CDN redirects
        cmd = ["wget"]
        if use_resume:
            cmd.append("-c")
        cmd.extend(["--progress=dot:mega", "--content-disposition", "-O", str(dest), download_url])
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        last_log = start
        stderr_lines: list[str] = []

        for line in iter(proc.stderr.readline, ""):
            line = line.rstrip()
            if not line:
                continue
            stderr_lines.append(line)

            now = _time.time()
            if "%" in line or "saved" in line.lower() or "error" in line.lower() or "failed" in line.lower():
                if now - last_log >= 3 or "100%" in line or "saved" in line.lower():
                    _logger.info(f"  [{lora_id}] {line}")
                    last_log = now
            elif "resolving" in line.lower() or "connecting" in line.lower() or "http request" in line.lower():
                _logger.info(f"  [{lora_id}] {line}")

        proc.wait(timeout=timeout)
        elapsed = _time.time() - start

        if proc.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
            file_size = dest.stat().st_size
            speed = file_size / elapsed if elapsed > 0 else 0
            _logger.info(
                f"  [{lora_id}] COMPLETE — {_fmt_bytes(file_size)} in {elapsed:.1f}s "
                f"({_fmt_bytes(int(speed))}/s)"
            )
            return {"id": lora_id, "name": name, "status": "installed", "size": file_size, "elapsed": round(elapsed, 1)}
        else:
            stderr_tail = "\n".join(stderr_lines[-5:]) if stderr_lines else "no output"
            _logger.error(
                f"  [{lora_id}] FAILED (exit code {proc.returncode}, {elapsed:.1f}s)\n"
                f"  Last output:\n{stderr_tail}"
            )
            # Clean up 0-byte or incomplete file left by wget on failure
            if dest.exists() and dest.stat().st_size == 0:
                _logger.info(f"  [{lora_id}] Removing 0-byte file from failed download")
                dest.unlink()
            return {"id": lora_id, "name": name, "status": "failed", "error": stderr_tail[-300:] if stderr_tail else "download failed"}

    except subprocess.TimeoutExpired:
        proc.kill()
        _logger.error(f"  [{lora_id}] TIMEOUT after {timeout}s")
        _cleanup_empty_file(dest, lora_id)
        return {"id": lora_id, "name": name, "status": "timeout"}
    except FileNotFoundError:
        _logger.error(f"  [{lora_id}] wget not found — install wget to enable downloads")
        return {"id": lora_id, "name": name, "status": "error", "error": "wget not found"}
    except Exception as e:
        _logger.error(f"  [{lora_id}] ERROR: {e}")
        _cleanup_empty_file(dest, lora_id)
        return {"id": lora_id, "name": name, "status": "error", "error": str(e)}


def _run_lora_download(lora_id: str, name: str, url: str, dest: Path, api_key: str = ""):
    """Background thread target: download one LoRA, then update shared state."""
    global _lora_download_state

    result = _download_lora_file(lora_id, name, url, dest, api_key=api_key)

    with _lora_download_lock:
        _lora_download_state["results"] = [result]
        _lora_download_state["finished"] = True
        _lora_download_state["running"] = False
        _lora_download_state["current_model"] = None


@router.post("/{lora_id}/install")
async def install_lora(lora_id: str):
    """Download and install a LoRA from the registry.

    Starts download in a background thread.
    Poll GET /v1/lora/download/status for progress.
    """
    global _lora_download_state

    # Prevent concurrent downloads
    with _lora_download_lock:
        if _lora_download_state["running"]:
            return {
                "ok": False,
                "error": "A LoRA download is already in progress. Check /v1/lora/download/status",
            }

    entry = get_lora_by_id(lora_id)
    if not entry:
        return {"ok": False, "error": f"Unknown LoRA: {lora_id}"}

    lora_dir = get_lora_dir()
    dest = lora_dir / entry.filename

    if dest.exists() and dest.stat().st_size > 0:
        return {"ok": True, "message": f"{entry.name} is already installed", "already_installed": True}

    # Clean up any leftover 0-byte file from a previous failed download
    if dest.exists() and dest.stat().st_size == 0:
        _logger.info(f"Removing leftover 0-byte file: {dest}")
        dest.unlink()

    if not entry.download_url:
        return {"ok": False, "error": f"No download URL configured for {entry.name}"}

    # Fetch CivitAI API key for gated/NSFW models
    civitai_api_key = ""
    if entry.gated and entry.source == "civitai":
        from ..api_keys import get_api_key
        civitai_api_key = get_api_key("civitai") or ""
        if not civitai_api_key:
            _logger.warning(f"No CivitAI API key configured for gated model {lora_id}")

    # Reset state
    with _lora_download_lock:
        _lora_download_state = {
            "running": True,
            "started_at": _time.time(),
            "current_model": lora_id,
            "current_index": 1,
            "total_models": 1,
            "results": [],
            "finished": False,
            "error": None,
        }

    thread = threading.Thread(
        target=_run_lora_download,
        args=(lora_id, entry.name, entry.download_url, dest, civitai_api_key),
        daemon=True,
        name=f"lora-dl-{lora_id}",
    )
    thread.start()

    _logger.info(f"LoRA download started: {lora_id} → {dest}")

    return {
        "ok": True,
        "message": f"Download started for {entry.name}. Poll /v1/lora/download/status for progress.",
        "model_id": lora_id,
    }


# ---------------------------------------------------------------------------
# Download status polling
# ---------------------------------------------------------------------------

@router.get("/download/status")
async def get_lora_download_status():
    """Poll LoRA download progress.

    Returns the same shape as avatar download status for frontend consistency.
    """
    with _lora_download_lock:
        state = dict(_lora_download_state)

    if state.get("started_at"):
        state["elapsed"] = round(_time.time() - state["started_at"], 1)
    else:
        state["elapsed"] = 0

    results = state.get("results", [])
    state["installed_count"] = sum(1 for r in results if r.get("status") in ("installed", "already_installed"))
    state["failed_count"] = sum(1 for r in results if r.get("status") not in ("installed", "already_installed", None))
    state["downloaded_bytes"] = sum(r.get("size", 0) for r in results if r.get("size"))

    return state


# ---------------------------------------------------------------------------
# Delete an installed LoRA
# ---------------------------------------------------------------------------

@router.delete("/{lora_id}")
async def delete_lora(lora_id: str):
    """Delete (uninstall) a LoRA file to free disk space.

    Only deletes files in the loras directory.
    """
    lora_dir = get_lora_dir()
    if not lora_dir.exists():
        return {"ok": False, "error": "LoRA directory does not exist"}

    # Find the file (check all supported extensions)
    target = None
    for f in lora_dir.iterdir():
        if f.stem == lora_id and f.suffix.lower() in (".safetensors", ".pt", ".ckpt"):
            target = f
            break

    if not target:
        return {"ok": False, "error": f"LoRA '{lora_id}' not found on disk"}

    try:
        size = target.stat().st_size
        target.unlink()
        _logger.info(f"Deleted LoRA: {target} ({_fmt_bytes(size)})")
        return {
            "ok": True,
            "model_id": lora_id,
            "name": lora_id,
            "deleted_files": [str(target)],
            "freed_bytes": size,
            "freed_human": _fmt_bytes(size),
        }
    except Exception as e:
        _logger.error(f"Failed to delete LoRA {lora_id}: {e}")
        return {"ok": False, "error": str(e)}
