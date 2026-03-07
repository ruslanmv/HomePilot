#!/usr/bin/env python3
"""
Download StyleGAN2 pre-trained weights for the avatar-service.

Supports multiple model sources ranked by quality and license:

  1. StyleGAN2-FFHQ-1024  (NVIDIA, non-commercial) — "This Person Does Not Exist" quality
  2. StyleGAN2-FFHQ-256   (NVIDIA, non-commercial) — smaller, faster, lower VRAM

Usage:
  python scripts/download_models.py                    # Interactive model picker
  python scripts/download_models.py --model ffhq-1024  # Download specific model
  python scripts/download_models.py --list              # List available models

The downloaded weights are placed in the models/ directory. Set
STYLEGAN_WEIGHTS_PATH in .env to point to the downloaded file.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

MODELS = {
    "ffhq-1024": {
        "title": "StyleGAN2 FFHQ 1024x1024",
        "description": "Full resolution — This Person Does Not Exist quality. ~360 MB.",
        "url": "https://nvlabs-fi-cdn.nvidia.com/stylegan2-ada-pytorch/pretrained/ffhq.pkl",
        "filename": "stylegan2-ffhq-1024x1024.pkl",
        "size_mb": 360,
        "resolution": 1024,
        "license": "NVIDIA Source Code License (Non-Commercial)",
        "sha256": None,  # Optional integrity check
    },
    "ffhq-256": {
        "title": "StyleGAN2 FFHQ 256x256",
        "description": "Compact model — faster inference, lower VRAM. ~170 MB.",
        "url": "https://nvlabs-fi-cdn.nvidia.com/stylegan2-ada-pytorch/pretrained/transfer-learning-source-nets/ffhq-res256-mirror-paper256-noaug.pkl",
        "filename": "stylegan2-ffhq-256x256.pkl",
        "size_mb": 170,
        "resolution": 256,
        "license": "NVIDIA Source Code License (Non-Commercial)",
        "sha256": None,
    },
}

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"


# ---------------------------------------------------------------------------
# Download logic
# ---------------------------------------------------------------------------

def download_file(url: str, dest: Path, expected_mb: int = 0) -> None:
    """Download a file with progress bar."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"  Already exists: {dest} ({size_mb:.1f} MB)")
        return

    print(f"  Downloading: {url}")
    print(f"  Destination: {dest}")
    if expected_mb:
        print(f"  Expected size: ~{expected_mb} MB")
    print()

    tmp = dest.with_suffix(".tmp")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "HomePilot-AvatarService/1.0"})
        with urllib.request.urlopen(req) as resp, open(tmp, "wb") as f:
            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            chunk_size = 1024 * 256  # 256 KB

            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)

                if total > 0:
                    pct = downloaded / total * 100
                    mb = downloaded / (1024 * 1024)
                    total_mb = total / (1024 * 1024)
                    bar_len = 40
                    filled = int(bar_len * downloaded / total)
                    bar = "=" * filled + "-" * (bar_len - filled)
                    print(f"\r  [{bar}] {pct:5.1f}% ({mb:.1f}/{total_mb:.1f} MB)", end="", flush=True)
                else:
                    mb = downloaded / (1024 * 1024)
                    print(f"\r  Downloaded: {mb:.1f} MB", end="", flush=True)

        print()  # Newline after progress
        tmp.rename(dest)
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"  Saved: {dest} ({size_mb:.1f} MB)")

    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def list_models() -> None:
    """Print available models."""
    print("\nAvailable StyleGAN2 models:\n")
    for key, info in MODELS.items():
        installed = (MODELS_DIR / info["filename"]).exists()
        status = " [INSTALLED]" if installed else ""
        print(f"  {key:12s}  {info['title']}{status}")
        print(f"               {info['description']}")
        print(f"               Resolution: {info['resolution']}x{info['resolution']}")
        print(f"               License: {info['license']}")
        print()


def download_model(key: str) -> Path:
    """Download a specific model and return its path."""
    if key not in MODELS:
        print(f"Error: Unknown model '{key}'. Available: {', '.join(MODELS.keys())}")
        sys.exit(1)

    info = MODELS[key]
    dest = MODELS_DIR / info["filename"]

    print(f"\n--- {info['title']} ---")
    print(f"    License: {info['license']}")
    print()

    download_file(info["url"], dest, info["size_mb"])

    print(f"\n  To use this model, set in your .env:")
    print(f"    STYLEGAN_ENABLED=true")
    print(f"    STYLEGAN_WEIGHTS_PATH={dest}")
    print()

    return dest


def interactive_picker() -> None:
    """Interactive model selection."""
    print("\n=== HomePilot Avatar Service — Model Downloader ===\n")
    print("Choose a model to download:\n")

    keys = list(MODELS.keys())
    for i, key in enumerate(keys):
        info = MODELS[key]
        installed = (MODELS_DIR / info["filename"]).exists()
        status = " [INSTALLED]" if installed else ""
        print(f"  [{i + 1}] {info['title']}{status}")
        print(f"      {info['description']}")
        print(f"      License: {info['license']}")
        print()

    print(f"  [0] Cancel\n")

    try:
        choice = input("Enter choice (1-{0}): ".format(len(keys))).strip()
        idx = int(choice) - 1
        if idx < 0:
            print("Cancelled.")
            return
        if idx >= len(keys):
            print("Invalid choice.")
            return
        download_model(keys[idx])
    except (ValueError, KeyboardInterrupt):
        print("\nCancelled.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Download StyleGAN2 models for HomePilot avatar generation")
    parser.add_argument("--model", choices=list(MODELS.keys()), help="Download a specific model")
    parser.add_argument("--list", action="store_true", help="List available models")
    parser.add_argument("--all", action="store_true", help="Download all models")
    args = parser.parse_args()

    if args.list:
        list_models()
    elif args.model:
        download_model(args.model)
    elif args.all:
        for key in MODELS:
            download_model(key)
    else:
        interactive_picker()


if __name__ == "__main__":
    main()
