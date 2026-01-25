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

try:
    import requests
    from tqdm import tqdm
except ImportError:
    print("ERROR: Missing required packages. Install with:")
    print("  pip install requests tqdm")
    sys.exit(1)

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
CATALOG_PATH = PROJECT_ROOT / "backend" / "app" / "model_catalog_data.json"

# ComfyUI models root - consistent with download_models.sh
COMFYUI_ROOT = PROJECT_ROOT / "models" / "comfy"

# Default install paths (relative to COMFYUI_ROOT)
# Note: The catalog's install_path takes precedence; these are fallbacks
INSTALL_PATHS = {
    "image": COMFYUI_ROOT / "checkpoints",
    "video": COMFYUI_ROOT / "checkpoints",
    "edit": COMFYUI_ROOT / "checkpoints",
}

CIVITAI_API_BASE = "https://civitai.com/api/v1"
CIVITAI_DOWNLOAD_BASE = "https://civitai.com/api/download/models"

DEFAULT_HEADERS = {
    "User-Agent": "HomePilot-Downloader/1.0",
}

def get_civitai_headers() -> Dict[str, str]:
    """Get headers for Civitai API requests, including API key if available."""
    headers = DEFAULT_HEADERS.copy()
    api_key = os.environ.get("CIVITAI_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        print("      Using Civitai API key from environment")
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
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_file = dest.with_suffix(dest.suffix + ".part")

    headers = custom_headers.copy() if custom_headers else DEFAULT_HEADERS.copy()

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

    # Step 2: Validate download URL
    print(f"[2/3] 🔗 Validating download source...")
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
    parser.add_argument("--type", choices=["chat", "image", "video", "edit"], help="Filter by model type")
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
