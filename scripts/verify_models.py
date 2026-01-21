#!/usr/bin/env python3
"""
HomePilot Model Verification Script

Verifies:
1. Model files exist in correct locations
2. Backend can detect installed models
3. Model scanning works correctly
4. ComfyUI can access models (via symlink)

Usage:
    python scripts/verify_models.py
"""

import sys
from pathlib import Path
from typing import List, Dict

# Add backend to path
backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from app.providers import get_comfy_models_path, scan_installed_models

def check_model_files() -> Dict[str, bool]:
    """Check which model files actually exist."""
    models_path = get_comfy_models_path()

    print(f"\n{'='*80}")
    print(f"Checking Model Files")
    print(f"{'='*80}\n")
    print(f"Models directory: {models_path}")
    print(f"Exists: {models_path.exists()}\n")

    # Define expected files
    expected_files = {
        "SDXL Base": models_path / "checkpoints" / "sd_xl_base_1.0.safetensors",
        "FLUX Schnell": models_path / "unet" / "flux1-schnell.safetensors",
        "FLUX Dev": models_path / "unet" / "flux1-dev.safetensors",
        "Pony XL": models_path / "checkpoints" / "ponyDiffusionV6XL.safetensors",
        "SD 1.5 (Dreamshaper)": models_path / "checkpoints" / "dreamshaper_8.safetensors",
        "SVD XT": models_path / "checkpoints" / "svd_xt.safetensors",
        "T5-XXL (CLIP)": models_path / "clip" / "t5xxl_fp16.safetensors",
        "CLIP-L": models_path / "clip" / "clip_l.safetensors",
        "FLUX VAE": models_path / "vae" / "ae.safetensors",
    }

    results = {}
    print("Model File Status:")
    print("-" * 80)

    for name, file_path in expected_files.items():
        exists = file_path.exists()
        size = file_path.stat().st_size / (1024**3) if exists else 0  # GB
        results[name] = exists

        status = "✅" if exists else "❌"
        size_str = f"({size:.2f} GB)" if exists else "(not found)"
        print(f"{status} {name:30s} {size_str:>15s}")

    return results

def check_model_scanning():
    """Test the model scanning function."""
    print(f"\n{'='*80}")
    print(f"Testing Model Scanning")
    print(f"{'='*80}\n")

    # Scan for image models
    image_models = scan_installed_models("image")
    print(f"Image models found: {len(image_models)}")
    for model in image_models:
        print(f"  - {model}")

    print()

    # Scan for video models
    video_models = scan_installed_models("video")
    print(f"Video models found: {len(video_models)}")
    for model in video_models:
        print(f"  - {model}")

def check_comfyui_symlink():
    """Check if ComfyUI symlink is set up correctly."""
    print(f"\n{'='*80}")
    print(f"Checking ComfyUI Integration")
    print(f"{'='*80}\n")

    repo_root = Path(__file__).parent.parent
    comfyui_models = repo_root / "ComfyUI" / "models"

    if not comfyui_models.exists():
        print("❌ ComfyUI/models does not exist")
        print("\nTo fix, run:")
        print(f"  rm -rf {repo_root}/ComfyUI/models")
        print(f"  ln -s {repo_root}/models/comfy {repo_root}/ComfyUI/models")
        return False

    if comfyui_models.is_symlink():
        target = comfyui_models.resolve()
        print(f"✅ ComfyUI/models is a symlink")
        print(f"   Points to: {target}")

        if target.exists():
            print(f"   Target exists: ✅")
            return True
        else:
            print(f"   Target exists: ❌")
            return False
    else:
        print(f"⚠️  ComfyUI/models is a directory (not symlink)")
        print(f"\nRecommended: Use symlink for HomePilot integration")
        print(f"  rm -rf {repo_root}/ComfyUI/models")
        print(f"  ln -s {repo_root}/models/comfy {repo_root}/ComfyUI/models")
        return False

def show_recommendations(file_results: Dict[str, bool]):
    """Show recommendations based on scan results."""
    print(f"\n{'='*80}")
    print(f"Recommendations")
    print(f"{'='*80}\n")

    # Check if any models are missing
    installed_models = [name for name, exists in file_results.items() if exists]

    if not installed_models:
        print("❌ No models found!")
        print("\nQuick start:")
        print("  1. Run: make download-recommended")
        print("  2. Wait for ~14GB download")
        print("  3. Run this script again")
    elif len(installed_models) < 3:
        print("⚠️  Only a few models installed")
        print("\nFor better experience:")
        print("  - FLUX models require: T5-XXL, CLIP-L, and VAE files")
        print("  - Run: make download-recommended")
    else:
        print("✅ Good! You have models installed")

        # Check if FLUX requirements are met
        has_flux = file_results.get("FLUX Schnell") or file_results.get("FLUX Dev")
        has_t5 = file_results.get("T5-XXL (CLIP)")
        has_clip = file_results.get("CLIP-L")
        has_vae = file_results.get("FLUX VAE")

        if has_flux and not (has_t5 and has_clip and has_vae):
            print("\n⚠️  FLUX models found but missing auxiliary files:")
            if not has_t5:
                print("  - Missing: T5-XXL text encoder")
            if not has_clip:
                print("  - Missing: CLIP-L text encoder")
            if not has_vae:
                print("  - Missing: FLUX VAE")
            print("\n  Run: make download-recommended")

def main():
    """Main verification function."""
    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║       HomePilot Model Verification Utility                 ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    # Run all checks
    file_results = check_model_files()
    check_model_scanning()
    check_comfyui_symlink()
    show_recommendations(file_results)

    print(f"\n{'='*80}")
    print("Verification Complete")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    main()
