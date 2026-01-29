#!/usr/bin/env python3
"""
HomePilot Model Downloader

Automatically download models from the catalog or Civitai (experimental).
Works with backend/app/model_catalog_data.json for curated models.

Usage:
    # Download a specific model from catalog
    python scripts/download.py --model sd_xl_base_1.0.safetensors

    # Download all image models from catalog
    python scripts/download.py --type image --all

    # Download from Civitai (experimental)
    python scripts/download.py --civitai --version-id 128713 --output dreamshaper_8.safetensors

    # List available models
    python scripts/download.py --list

    # Add Civitai model to catalog (experimental)
    python scripts/download.py --add-civitai --version-id 128713 --type image
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
import shutil

try:
    import requests
    from tqdm import tqdm
except ImportError:
    print("ERROR: Missing required packages. Install with:")
    print("  pip install requests tqdm")
    sys.exit(1)

# Optional dependency: only required for HF-based installs (model packs)
try:
    from huggingface_hub import hf_hub_download, snapshot_download  # type: ignore
    _HAS_HF = True
except Exception:
    hf_hub_download = None
    snapshot_download = None
    _HAS_HF = False

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
CATALOG_PATH = PROJECT_ROOT / "backend" / "app" / "model_catalog_data.json"

# ComfyUI models root - consistent with download_models.sh
COMFYUI_ROOT = PROJECT_ROOT / "models" / "comfy"

# ComfyUI installation root (for custom_nodes)
def get_comfyui_install_root() -> Path:
    """
    Find the ComfyUI installation directory (where custom_nodes lives).
    Checks common locations in order of priority.
    """
    candidates = [
        PROJECT_ROOT / "ComfyUI",           # Local development
        Path("/ComfyUI"),                   # Docker container
        Path.home() / "ComfyUI",            # Home directory
        Path("/mnt/c/workspace/homegrok/homepilot/ComfyUI"),  # WSL specific
    ]
    for p in candidates:
        if p.exists() and (p / "custom_nodes").exists():
            return p
    # Fallback to first candidate (will create if needed)
    return candidates[0]

# Default install paths (relative to COMFYUI_ROOT)
# Note: The catalog's install_path takes precedence; these are fallbacks
INSTALL_PATHS = {
    "image": COMFYUI_ROOT / "checkpoints",
    "video": COMFYUI_ROOT / "checkpoints",
    "edit": COMFYUI_ROOT / "checkpoints",
    "enhance": COMFYUI_ROOT / "upscale_models",
}

CIVITAI_API_BASE = "https://civitai.com/api/v1"
CIVITAI_DOWNLOAD_BASE = "https://civitai.com/api/download/models"

DEFAULT_HEADERS = {
    "User-Agent": "HomePilot-Downloader/1.0",
}

# Storage for API keys (same location as backend)
ENV_JSON_FILE = PROJECT_ROOT / "backend" / ".env.json"


# -----------------------------------------------------------------------------
# API Keys Support (Optional - for gated models)
# -----------------------------------------------------------------------------

def get_stored_api_key(provider: str) -> Optional[str]:
    """
    Read API key from HomePilot's stored keys (.env.json).
    Returns None if not configured (this is normal - keys are optional).
    """
    if not ENV_JSON_FILE.exists():
        return None
    try:
        with open(ENV_JSON_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            api_keys = data.get("api_keys", {})
            key = api_keys.get(provider, "").strip()
            return key if key else None
    except (json.JSONDecodeError, IOError):
        return None


def get_hf_token() -> Optional[str]:
    """
    Get HuggingFace token.
    Priority: Environment variable > Stored key
    Returns None if not configured (keys are optional).
    """
    env_token = os.getenv("HF_TOKEN", "").strip()
    if env_token:
        return env_token
    return get_stored_api_key("huggingface")


def get_civitai_key() -> Optional[str]:
    """
    Get Civitai API key.
    Priority: Environment variable > Stored key
    Returns None if not configured (keys are optional).
    """
    env_key = os.getenv("CIVITAI_API_KEY", "").strip()
    if env_key:
        return env_key
    return get_stored_api_key("civitai")


# -----------------------------------------------------------------------------
# Hugging Face / Model Pack Support
# -----------------------------------------------------------------------------

def _need_hf() -> None:
    """Check if huggingface_hub is installed, exit with error if not."""
    if not _HAS_HF:
        print("ERROR: This model requires Hugging Face downloads, but huggingface_hub is not installed.")
        print("Install it with:")
        print("  pip install huggingface_hub")
        sys.exit(1)


def normalize_rel_path(p: str) -> str:
    """
    Normalize legacy catalog paths.
    - If a path starts with 'models/', strip it.
    - Return a clean relative path (no leading slash).
    """
    p = p.replace("\\", "/")
    if p.startswith("models/"):
        p = p[len("models/"):]
    p = p.lstrip("/")
    return p


def comfy_dest_path(rel_dest: str) -> Path:
    """
    Convert a relative model destination (inside ComfyUI models root) into a Path.
    HomePilot's ComfyUI root is PROJECT_ROOT/models/comfy
    """
    rel_dest = normalize_rel_path(rel_dest)
    return COMFYUI_ROOT / rel_dest


def hf_download_to(repo_id: str, filename: str, dest: Path) -> None:
    """
    Download a specific file from Hugging Face and copy it into dest.
    Uses HF cache for the actual download, then copies to ComfyUI folder.

    Token priority:
    1. HF_TOKEN environment variable
    2. Stored key in .env.json
    3. None (anonymous download for public repos)
    """
    _need_hf()
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Get token from env or stored keys, None allows anonymous download for public repos
    token = get_hf_token()
    src_path = hf_hub_download(repo_id=repo_id, filename=filename, token=token)
    shutil.copy2(src_path, dest)


def hf_snapshot_to(repo_id: str, dest_dir: Path, allow_patterns: Optional[List[str]] = None) -> None:
    """
    Download an entire Hugging Face repo snapshot into dest_dir (Diffusers-style repos).

    Token priority:
    1. HF_TOKEN environment variable
    2. Stored key in .env.json
    3. None (anonymous download for public repos)
    """
    _need_hf()
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Get token from env or stored keys, None allows anonymous download for public repos
    token = get_hf_token()
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(dest_dir),
        local_dir_use_symlinks=False,
        allow_patterns=allow_patterns,
        token=token,
    )


def install_from_install_block(model_id: str, model_data: Dict[str, Any]) -> bool:
    """
    New behavior: support install packs and HF sources.
    Returns True if handled, False if caller should fallback to download_url flow.

    Supported install types:
      - hf_files: list of files from HF repos -> ComfyUI folder destinations
      - hf_snapshot: download a whole repo snapshot into a target directory
      - http_files: list of direct URLs -> destinations (uses existing download_file)
    """
    install = model_data.get("install")
    if not isinstance(install, dict):
        return False

    install_type = install.get("type")

    # ----------------------------
    # hf_files (multi-file packs)
    # ----------------------------
    if install_type == "hf_files":
        files = install.get("files")
        if not isinstance(files, list) or not files:
            print(f"ERROR: install.type=hf_files but no install.files[] for model: {model_id}")
            sys.exit(1)

        print(f"      Pack contains {len(files)} files")

        for idx, f in enumerate(files, start=1):
            if not isinstance(f, dict):
                continue
            repo_id = f.get("repo_id")
            filename = f.get("filename")
            dest_rel = f.get("dest")
            sha256 = f.get("sha256")
            url = f.get("url")  # optional override for non-HF sources

            if not dest_rel:
                print(f"ERROR: Missing dest in install.files entry (index {idx})")
                sys.exit(1)

            dest = comfy_dest_path(dest_rel)

            if dest.exists():
                print(f"      [Exists] {dest_rel}")
                continue

            print(f"      [{idx}/{len(files)}] {dest_rel}")
            if url:
                ok, msg = download_file(url, dest)
                if not ok:
                    print(f"ERROR: {msg}")
                    sys.exit(1)
            else:
                if not repo_id or not filename:
                    print(f"ERROR: Missing repo_id/filename for install.files entry (index {idx})")
                    sys.exit(1)
                hf_download_to(repo_id=repo_id, filename=filename, dest=dest)

            if sha256:
                if not verify_sha256(dest, sha256):
                    print(f"ERROR: SHA256 mismatch for {dest.name}")
                    sys.exit(1)

        hint = install.get("hint")
        if hint:
            print(f"\n      Note: {hint}")
        req_nodes = install.get("requires_custom_nodes")
        if req_nodes:
            print("\n      Required ComfyUI custom nodes:")
            for n in req_nodes:
                print(f"        - {n}")
        return True

    # ----------------------------
    # http_files (multi direct URLs)
    # ----------------------------
    if install_type == "http_files":
        files = install.get("files")
        if not isinstance(files, list) or not files:
            print(f"ERROR: install.type=http_files but no install.files[] for model: {model_id}")
            sys.exit(1)

        print(f"      Pack contains {len(files)} files")
        for idx, f in enumerate(files, start=1):
            url = f.get("url")
            dest_rel = f.get("dest")
            sha256 = f.get("sha256")
            if not url or not dest_rel:
                print(f"ERROR: http_files entries require url + dest (index {idx})")
                sys.exit(1)
            dest = comfy_dest_path(dest_rel)
            if dest.exists():
                print(f"      [Exists] {dest_rel}")
                continue
            print(f"      [{idx}/{len(files)}] {dest_rel}")
            ok, msg = download_file(url, dest)
            if not ok:
                print(f"ERROR: {msg}")
                sys.exit(1)
            if sha256 and not verify_sha256(dest, sha256):
                print(f"ERROR: SHA256 mismatch for {dest.name}")
                sys.exit(1)

        hint = install.get("hint")
        if hint:
            print(f"\n      Note: {hint}")
        req_nodes = install.get("requires_custom_nodes")
        if req_nodes:
            print("\n      Required ComfyUI custom nodes:")
            for n in req_nodes:
                print(f"        - {n}")
        return True

    # ----------------------------
    # hf_snapshot (Diffusers repos)
    # ----------------------------
    if install_type == "hf_snapshot":
        repo_id = install.get("repo_id")
        dest_rel = install.get("dest_dir")
        allow_patterns = install.get("allow_patterns")  # optional
        if not repo_id or not dest_rel:
            print(f"ERROR: hf_snapshot requires install.repo_id and install.dest_dir for model: {model_id}")
            sys.exit(1)
        dest_dir = comfy_dest_path(dest_rel)
        print(f"      Snapshot download: {repo_id} -> {dest_dir}")
        hf_snapshot_to(repo_id=repo_id, dest_dir=dest_dir, allow_patterns=allow_patterns)

        hint = install.get("hint")
        if hint:
            print(f"\n      Note: {hint}")
        req_nodes = install.get("requires_custom_nodes")
        if req_nodes:
            print("\n      Required ComfyUI custom nodes:")
            for n in req_nodes:
                print(f"        - {n}")
        return True

    if install_type == "git_repo":
        repo_url = install.get("repo_url")
        dest_rel = install.get("dest_dir")
        if not repo_url or not dest_rel:
            print(f"ERROR: git_repo requires repo_url and dest_dir for model: {model_id}")
            sys.exit(1)

        # Normalize and validate the destination path
        dest_rel = normalize_rel_path(dest_rel)
        if dest_rel.startswith(".."):
            print(f"ERROR: invalid dest_dir path (directory traversal not allowed): {dest_rel}")
            sys.exit(1)

        # For custom_nodes, install relative to ComfyUI root
        comfyui_root = get_comfyui_install_root()
        dest_dir = comfyui_root / dest_rel
        dest_dir.parent.mkdir(parents=True, exist_ok=True)

        if dest_dir.exists():
            # Check if it's a non-empty directory (already installed)
            try:
                if any(dest_dir.iterdir()):
                    print(f"      [Exists] {dest_rel}")
                    hint = install.get("hint")
                    if hint:
                        print(f"      Note: {hint}")
                    return True
            except Exception:
                pass

        print(f"      Cloning {repo_url}")
        print(f"      -> {dest_dir}")

        try:
            import subprocess
            result = subprocess.run(
                ["git", "clone", "--depth", "1", repo_url, str(dest_dir)],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                print(f"ERROR: git clone failed: {result.stderr}")
                sys.exit(1)
            print("      Clone successful!")
        except FileNotFoundError:
            print("ERROR: git is not installed. Please install git and try again.")
            sys.exit(1)

        hint = install.get("hint")
        if hint:
            print(f"\n      Note: {hint}")
        return True

    # Unknown install type -> fallback to download_url
    return False


def get_civitai_headers() -> Dict[str, str]:
    """
    Get headers for Civitai API requests, including API key if available.

    API key priority:
    1. CIVITAI_API_KEY environment variable
    2. Stored key in .env.json
    """
    headers = DEFAULT_HEADERS.copy()
    api_key = get_civitai_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        source = "environment" if os.environ.get("CIVITAI_API_KEY") else "stored settings"
        print(f"      Using Civitai API key from {source}")
    return headers

# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------

def load_catalog() -> Dict[str, Any]:
    """Load the model catalog JSON."""
    if not CATALOG_PATH.exists():
        print(f"ERROR: Catalog not found at {CATALOG_PATH}")
        sys.exit(1)

    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_catalog(catalog: Dict[str, Any]) -> None:
    """Save the model catalog JSON."""
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    print(f"✓ Catalog saved to {CATALOG_PATH}")


def get_install_path(model_type: str, custom_path: Optional[str] = None) -> Path:
    """Get the installation path for a model type."""
    if custom_path:
        return Path(custom_path)

    path = INSTALL_PATHS.get(model_type)
    if not path:
        raise ValueError(f"Unknown model type: {model_type}")

    path.mkdir(parents=True, exist_ok=True)
    return path


def download_file(
    url: str,
    dest: Path,
    expected_size: Optional[int] = None,
    show_progress: bool = True,
    resume: bool = True,
    custom_headers: Optional[Dict[str, str]] = None,
) -> Tuple[bool, str]:
    """
    Download a file with progress bar and resume support.
    Returns (success, message).

    Automatically adds authentication headers for:
    - HuggingFace URLs (uses HF_TOKEN env var or stored key)
    - Civitai URLs (uses custom_headers passed by caller)
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_file = dest.with_suffix(dest.suffix + ".part")

    headers = custom_headers.copy() if custom_headers else DEFAULT_HEADERS.copy()

    # Automatically add HuggingFace authentication for gated models
    if "huggingface.co/" in url and "/resolve/" in url:
        hf_token = get_hf_token()
        if hf_token and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {hf_token}"

    # Resume support
    start_pos = 0
    if resume and temp_file.exists():
        start_pos = temp_file.stat().st_size
        headers["Range"] = f"bytes={start_pos}-"

    try:
        response = requests.get(url, headers=headers, stream=True, timeout=30)
        response.raise_for_status()

        # Check if server supports resume
        if start_pos > 0 and response.status_code == 200:
            # Server doesn't support resume, start over
            start_pos = 0
            temp_file.unlink(missing_ok=True)

        total_size = int(response.headers.get("content-length", 0))
        if start_pos > 0:
            total_size += start_pos

        mode = "ab" if start_pos > 0 else "wb"

        if show_progress and total_size > 0:
            progress = tqdm(
                total=total_size,
                initial=start_pos,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                desc=dest.name,
            )

        with open(temp_file, mode) as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    if show_progress and total_size > 0:
                        progress.update(len(chunk))

        if show_progress and total_size > 0:
            progress.close()

        # Move to final location
        temp_file.replace(dest)

        return True, f"Downloaded {dest.name} ({total_size / (1024**2):.1f} MB)"

    except requests.exceptions.HTTPError as e:
        # Provide helpful message for HuggingFace authentication errors
        if e.response is not None and e.response.status_code == 401 and "huggingface.co" in url:
            hf_token = get_hf_token()
            if not hf_token:
                return False, (
                    f"Failed to download: 401 Unauthorized - This is a gated HuggingFace model.\n"
                    f"         To download gated models:\n"
                    f"         1. Accept the license at: https://huggingface.co/{url.split('huggingface.co/')[1].split('/resolve')[0]}\n"
                    f"         2. Create a HuggingFace token at: https://huggingface.co/settings/tokens\n"
                    f"         3. Set HF_TOKEN environment variable OR configure in HomePilot Settings > API Keys"
                )
            else:
                return False, (
                    f"Failed to download: 401 Unauthorized - HuggingFace token provided but access denied.\n"
                    f"         Please ensure you have accepted the model license at:\n"
                    f"         https://huggingface.co/{url.split('huggingface.co/')[1].split('/resolve')[0]}"
                )
        return False, f"Failed to download: {str(e)}"
    except Exception as e:
        return False, f"Failed to download: {str(e)}"


def verify_sha256(file_path: Path, expected: str) -> bool:
    """Verify file SHA256 hash."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)

    actual = sha256.hexdigest()
    return actual.lower() == expected.lower()


# -----------------------------------------------------------------------------
# Catalog Operations
# -----------------------------------------------------------------------------

def list_catalog_models(model_type: Optional[str] = None) -> None:
    """List all models in the catalog."""
    catalog = load_catalog()
    providers = catalog.get("providers", {})

    print("\n" + "="*80)
    print("MODEL CATALOG")
    print("="*80 + "\n")

    for provider_name, provider_data in providers.items():
        for type_name, models in provider_data.items():
            if model_type and type_name != model_type:
                continue

            print(f"\n{provider_name.upper()} - {type_name.upper()}")
            print("-" * 80)

            for model in models:
                status = "⭐" if model.get("recommended") else "  "
                name = model.get("label", model.get("id"))
                model_id = model.get("id")
                size = model.get("size_gb", "?")

                print(f"{status} {name}")
                print(f"   ID: {model_id}")
                print(f"   Size: {size} GB")

                if model.get("download_url"):
                    print(f"   Download: {model.get('download_url')}")

                print()


def find_model_in_catalog(model_id: str) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """
    Find a model in the catalog by ID.
    Returns (provider, type, model_data) or None.
    """
    catalog = load_catalog()
    providers = catalog.get("providers", {})

    for provider_name, provider_data in providers.items():
        for type_name, models in provider_data.items():
            for model in models:
                if model.get("id") == model_id:
                    return provider_name, type_name, model

    return None


def download_catalog_model(model_id: str, output_dir: Optional[str] = None) -> int:
    """Download a model from the catalog."""
    print(f"\n{'='*80}")
    print(f"📦 Model Download from Catalog")
    print(f"{'='*80}")
    print(f"Model ID: {model_id}")
    print()

    # Step 1: Find in catalog
    print(f"[1/3] 🔍 Looking up model in catalog...")
    result = find_model_in_catalog(model_id)
    if not result:
        print(f"      ✗ Model '{model_id}' not found in catalog")
        print(f"\n💡 Try: python scripts/download.py --list")
        return 1

    provider, model_type, model_data = result
    print(f"      ✓ Found in catalog")
    print(f"      Provider: {provider}")
    print(f"      Type: {model_type}")
    print(f"      Name: {model_data.get('label', model_id)}")
    print()

    # Step 2: Validate download source (supports install packs OR download_url)
    print(f"[2/3] 🔗 Validating download source...")

    # If this entry has an install block (packs / HF downloads), run it
    if provider == "comfyui" and isinstance(model_data.get("install"), dict):
        print("      Install method: catalog install block")
        handled = install_from_install_block(model_id=model_id, model_data=model_data)
        if handled:
            print()
            print(f"{'='*80}")
            print("SUCCESS: Model pack installed")
            print(f"{'='*80}")
            return 0

    download_url = model_data.get("download_url")
    if not download_url:
        print(f"      ✗ No download URL for model '{model_id}'")
        print(f"      This model may require manual download from the provider.")
        return 1

    print(f"      URL: {download_url[:60]}..." if len(download_url) > 60 else f"      URL: {download_url}")

    # Determine output path
    if output_dir:
        dest_path = Path(output_dir) / model_id
        print(f"      Using custom directory: {output_dir}")
    else:
        install_path = model_data.get("install_path", "checkpoints/")
        # Strip "models/" prefix if present (legacy catalog format)
        if install_path.startswith("models/"):
            install_path = install_path[7:]  # Remove "models/" prefix

        if provider == "comfyui":
            base_path = COMFYUI_ROOT / install_path
        else:
            base_path = get_install_path(model_type)

        dest_path = base_path / model_id
        print(f"      Install path: {base_path}")

    print(f"      Destination: {dest_path}")

    size_gb = model_data.get('size_gb', '?')
    print(f"      Expected size: {size_gb} GB")
    print(f"      ✓ Download prepared")
    print()

    # Step 3: Download
    print(f"[3/3] ⬇️  Downloading model...")
    print(f"      Starting download... (this may take several minutes for large models)")
    print()

    success, message = download_file(download_url, dest_path)

    print()
    print(f"{'='*80}")
    if success:
        print(f"✅ SUCCESS: {message}")

        # Verify hash if provided
        if model_data.get("sha256"):
            print()
            print(f"🔐 Verifying file integrity (SHA256)...")
            if verify_sha256(dest_path, model_data["sha256"]):
                print(f"✓ Hash verified - file is authentic")
            else:
                print(f"✗ Hash verification failed - file may be corrupted!")
                print(f"{'='*80}")
                return 1

        print(f"{'='*80}")
        print(f"\n📦 Model installed to: {dest_path}")
        return 0
    else:
        print(f"❌ FAILED: {message}")
        print(f"{'='*80}")
        print(f"\n💡 Troubleshooting:")
        print(f"   - Check your internet connection")
        print(f"   - Verify disk space is sufficient ({size_gb} GB required)")
        print(f"   - Try again - downloads support resume")
        return 1


# -----------------------------------------------------------------------------
# Civitai Integration (Experimental)
# -----------------------------------------------------------------------------

def civitai_get_version_info(version_id: str) -> Optional[Dict[str, Any]]:
    """Fetch model version info from Civitai API."""
    url = f"{CIVITAI_API_BASE}/model-versions/{version_id}"

    try:
        headers = get_civitai_headers()
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"ERROR: Failed to fetch Civitai version info: {e}")
        return None


def download_civitai_model(
    version_id: str,
    output_path: Optional[str] = None,
    model_type: str = "image",
) -> int:
    """Download a model from Civitai (experimental)."""
    print(f"\n{'='*80}")
    print(f"🧪 EXPERIMENTAL: Civitai Model Download")
    print(f"{'='*80}")
    print(f"Version ID: {version_id}")
    print(f"Model Type: {model_type}")
    print()

    # Step 1: Fetch version info
    print(f"[1/4] 🔍 Fetching model information from Civitai API...")
    print(f"      API: {CIVITAI_API_BASE}/model-versions/{version_id}")
    info = civitai_get_version_info(version_id)
    if not info:
        print(f"      ✗ Failed to fetch model info")
        return 1
    print(f"      ✓ Model info retrieved successfully")
    print()

    # Step 2: Parse model metadata
    print(f"[2/4] 📋 Parsing model metadata...")
    model_info = info.get("model", {})
    model_name = model_info.get("name", "unknown")
    model_id = model_info.get("id")
    version_name = info.get("name", "")

    print(f"      Model Name: {model_name}")
    print(f"      Model ID: {model_id}")
    if version_name:
        print(f"      Version: {version_name}")

    # Get best file
    files = info.get("files", [])
    if not files:
        print(f"      ✗ No files found for this version")
        return 1

    print(f"      Files available: {len(files)}")

    # Prefer primary safetensors file
    best_file = None
    for f in files:
        if f.get("primary"):
            best_file = f
            break

    if not best_file:
        best_file = files[0]

    file_name = best_file.get("name", f"civitai_{version_id}.safetensors")
    file_size_mb = best_file.get("sizeKB", 0) / 1024
    file_type = best_file.get("type", "Model")

    print(f"      Selected file: {file_name}")
    print(f"      File type: {file_type}")
    print(f"      File size: {file_size_mb:.1f} MB ({file_size_mb / 1024:.2f} GB)")
    print(f"      ✓ Metadata parsed successfully")
    print()

    # Step 3: Determine output path
    print(f"[3/4] 📁 Determining installation path...")
    download_url = f"{CIVITAI_DOWNLOAD_BASE}/{version_id}"

    if output_path:
        dest_path = Path(output_path)
        print(f"      Using custom path: {dest_path}")
    else:
        base_path = get_install_path(model_type)
        dest_path = base_path / file_name
        print(f"      Install path: {base_path}")
        print(f"      Full destination: {dest_path}")

    # Check if file already exists
    if dest_path.exists():
        existing_size = dest_path.stat().st_size / (1024 * 1024)
        print(f"      ⚠️  File already exists ({existing_size:.1f} MB)")
        print(f"      Download will resume if partial, or overwrite if needed")

    print(f"      ✓ Path configured")
    print()

    # Step 4: Download
    print(f"[4/4] ⬇️  Downloading model from Civitai...")
    print(f"      URL: {download_url}")
    print(f"      Starting download... (this may take several minutes for large models)")
    print()

    # Use Civitai headers (includes API key if available)
    civitai_headers = get_civitai_headers()
    success, message = download_file(download_url, dest_path, custom_headers=civitai_headers)

    print()
    print(f"{'='*80}")
    if success:
        print(f"✅ SUCCESS: {message}")
        print(f"{'='*80}")
        print(f"\n📦 Model installed to: {dest_path}")
        print(f"✨ You can now use this model in ComfyUI!")
        return 0
    else:
        print(f"❌ FAILED: {message}")
        print(f"{'='*80}")
        print(f"\n💡 Troubleshooting:")
        print(f"   - Check your internet connection")
        print(f"   - Verify the version ID is correct: {version_id}")
        print(f"   - Some models may require a Civitai API key")
        print(f"   - Try again - downloads support resume")
        return 1


def add_civitai_to_catalog(version_id: str, model_type: str) -> int:
    """Add a Civitai model to the catalog (experimental)."""
    print(f"\n🧪 EXPERIMENTAL: Adding Civitai model to catalog")

    # Fetch version info
    info = civitai_get_version_info(version_id)
    if not info:
        return 1

    # Get model info
    model_info = info.get("model", {})
    model_name = model_info.get("name", "Unknown")
    model_id = str(model_info.get("id", version_id))

    # Get best file
    files = info.get("files", [])
    if not files:
        print("ERROR: No files found for this version")
        return 1

    best_file = None
    for f in files:
        if f.get("primary"):
            best_file = f
            break

    if not best_file:
        best_file = files[0]

    file_name = best_file.get("name", f"civitai_{version_id}.safetensors")
    size_gb = best_file.get("sizeKB", 0) / (1024 * 1024)

    # Create catalog entry
    entry = {
        "id": file_name,
        "label": f"{model_name} (Civitai)",
        "description": f"Downloaded from Civitai. Model ID: {model_id}",
        "size_gb": round(size_gb, 2),
        "download_url": f"{CIVITAI_DOWNLOAD_BASE}/{version_id}",
        "install_path": "checkpoints/",
        "civitai_version_id": version_id,
        "civitai_model_id": model_id,
    }

    # Load catalog
    catalog = load_catalog()

    # Add to ComfyUI models
    if "comfyui" not in catalog["providers"]:
        catalog["providers"]["comfyui"] = {}

    if model_type not in catalog["providers"]["comfyui"]:
        catalog["providers"]["comfyui"][model_type] = []

    # Check if already exists
    for existing in catalog["providers"]["comfyui"][model_type]:
        if existing.get("id") == file_name:
            print(f"Model '{file_name}' already exists in catalog")
            print("Updating entry...")
            catalog["providers"]["comfyui"][model_type].remove(existing)
            break

    catalog["providers"]["comfyui"][model_type].append(entry)

    # Save catalog
    save_catalog(catalog)

    print(f"\n✓ Added to catalog:")
    print(f"  ID: {file_name}")
    print(f"  Name: {model_name}")
    print(f"  Type: {model_type}")
    print(f"  Size: {size_gb:.2f} GB")

    return 0


# -----------------------------------------------------------------------------
# Batch Operations
# -----------------------------------------------------------------------------

def download_all_type(model_type: str, output_dir: Optional[str] = None) -> int:
    """Download all models of a specific type."""
    catalog = load_catalog()
    providers = catalog.get("providers", {})

    models_to_download = []

    for provider_name, provider_data in providers.items():
        for type_name, models in provider_data.items():
            if type_name == model_type:
                for model in models:
                    if model.get("download_url"):
                        models_to_download.append((provider_name, type_name, model))

    if not models_to_download:
        print(f"No downloadable models found for type '{model_type}'")
        return 1

    print(f"\nFound {len(models_to_download)} models to download")
    print("="*80 + "\n")

    success_count = 0
    failed_count = 0

    for i, (provider, mtype, model) in enumerate(models_to_download, 1):
        model_id = model.get("id")
        print(f"\n[{i}/{len(models_to_download)}] Downloading: {model_id}")
        print("-"*80)

        result = download_catalog_model(model_id, output_dir)
        if result == 0:
            success_count += 1
        else:
            failed_count += 1

        print()

    print("\n" + "="*80)
    print(f"SUMMARY: {success_count} succeeded, {failed_count} failed")
    print("="*80)

    return 0 if failed_count == 0 else 1


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="HomePilot Model Downloader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Actions
    parser.add_argument("--list", action="store_true", help="List all models in catalog")
    parser.add_argument("--model", help="Download specific model by ID")
    parser.add_argument("--type", choices=["chat", "image", "video", "edit", "enhance"], help="Filter by model type")
    parser.add_argument("--all", action="store_true", help="Download all models of specified type")

    # Civitai (experimental)
    parser.add_argument("--civitai", action="store_true", help="🧪 Download from Civitai")
    parser.add_argument("--version-id", help="Civitai model version ID")
    parser.add_argument("--add-civitai", action="store_true", help="🧪 Add Civitai model to catalog")

    # Output
    parser.add_argument("--output", "-o", help="Custom output path")
    parser.add_argument("--output-dir", help="Custom output directory for batch downloads")

    args = parser.parse_args()

    # List models
    if args.list:
        list_catalog_models(args.type)
        return 0

    # Add Civitai to catalog
    if args.add_civitai:
        if not args.version_id:
            print("ERROR: --version-id required for --add-civitai")
            return 1
        if not args.type:
            print("ERROR: --type required for --add-civitai")
            return 1
        return add_civitai_to_catalog(args.version_id, args.type)

    # Download from Civitai
    if args.civitai:
        if not args.version_id:
            print("ERROR: --version-id required for --civitai")
            return 1
        return download_civitai_model(
            args.version_id,
            args.output,
            args.type or "image",
        )

    # Download specific model
    if args.model:
        return download_catalog_model(args.model, args.output_dir)

    # Download all of type
    if args.all:
        if not args.type:
            print("ERROR: --type required for --all")
            return 1
        return download_all_type(args.type, args.output_dir)

    # No action specified
    parser.print_help()
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(130)
