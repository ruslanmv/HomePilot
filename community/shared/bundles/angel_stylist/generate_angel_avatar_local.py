#!/usr/bin/env python3
"""
generate_angel_avatar_local.py — Generate realistic faces using local GPU
=========================================================================

Uses HomePilot's built-in StyleGAN2 FFHQ 1024 model to generate the same
photorealistic faces as https://thispersondoesnotexist.com — entirely
offline, on your own GPU (or CPU fallback).

This is the local equivalent of generate_angel_avatar.py, which fetches
faces from the website. This script runs the exact same NVIDIA StyleGAN2
model locally for full control, reproducibility (seed-based), and privacy.

Prerequisites:
  1. PyTorch installed (pip install torch)
  2. Model weights downloaded:
       python avatar-service/scripts/download_models.py --model ffhq-1024

Usage:
  # Generate 6 candidates, pick the best interactively
  python generate_angel_avatar_local.py --candidates 6

  # Generate a specific face by seed (deterministic — same seed = same face)
  python generate_angel_avatar_local.py --seed 42

  # Generate with specific truncation (lower = more average, higher = diverse)
  python generate_angel_avatar_local.py --seed 42 --truncation 0.5

  # Use a specific weights file
  python generate_angel_avatar_local.py --weights /path/to/stylegan2-ffhq-1024x1024.pkl

  # CPU-only (slower but works without NVIDIA GPU)
  python generate_angel_avatar_local.py --device cpu --seed 42

  # Auto-pick: generate N faces and select the first one (non-interactive)
  python generate_angel_avatar_local.py --candidates 1 --pick 1
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import sys
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PERSONA_DIR = SCRIPT_DIR / "persona"
ASSETS_DIR = PERSONA_DIR / "assets"
AVATAR_FILENAME = "avatar_angel.png"
THUMB_FILENAME = "thumb_avatar_angel.webp"

# Default search paths for StyleGAN2 weights (checked in order)
WEIGHTS_SEARCH_PATHS = [
    # Avatar-service models directory
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "avatar-service" / "models" / "stylegan2-ffhq-1024x1024.pkl",
    # ComfyUI models directory
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "models" / "comfy" / "avatar" / "stylegan2-ffhq-1024x1024.pkl",
    # Docker volume mount path
    Path("/models/stylegan2-ffhq-1024x1024.pkl"),
    # 256 fallback
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "avatar-service" / "models" / "stylegan2-ffhq-256x256.pkl",
]

DOWNLOAD_URLS = {
    "ffhq-1024": {
        "url": "https://nvlabs-fi-cdn.nvidia.com/stylegan2-ada-pytorch/pretrained/ffhq.pkl",
        "filename": "stylegan2-ffhq-1024x1024.pkl",
        "size_mb": 360,
    },
    "ffhq-256": {
        "url": "https://nvlabs-fi-cdn.nvidia.com/stylegan2-ada-pytorch/pretrained/"
               "transfer-learning-source-nets/ffhq-res256-mirror-paper256-noaug.pkl",
        "filename": "stylegan2-ffhq-256x256.pkl",
        "size_mb": 170,
    },
}


# ---------------------------------------------------------------------------
# StyleGAN2 local inference
# ---------------------------------------------------------------------------

def find_weights(explicit_path: str | None = None) -> Path:
    """Locate StyleGAN2 weights on disk."""
    if explicit_path:
        p = Path(explicit_path)
        if p.exists():
            return p
        print(f"  [ERROR] Specified weights not found: {p}")
        sys.exit(1)

    # Check environment variable (matches avatar-service config)
    env_path = os.getenv("STYLEGAN_WEIGHTS_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    # Search default locations
    for p in WEIGHTS_SEARCH_PATHS:
        if p.exists():
            return p

    # Not found — show download instructions
    print("  [ERROR] StyleGAN2 weights not found.")
    print()
    print("  Download them with:")
    print("    python avatar-service/scripts/download_models.py --model ffhq-1024")
    print()
    print("  Or manually download from NVIDIA:")
    for key, info in DOWNLOAD_URLS.items():
        print(f"    {key}: {info['url']}")
    print()
    print("  Then pass the path: --weights /path/to/stylegan2-ffhq-1024x1024.pkl")
    sys.exit(1)


def load_stylegan2(weights_path: Path, device: str = "auto"):
    """Load StyleGAN2 generator using HomePilot's avatar-service loader."""
    import torch

    # Resolve device
    if device == "auto":
        dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        dev = torch.device(device)

    print(f"  Device: {dev}")
    print(f"  Weights: {weights_path}")
    print(f"  Loading model...")

    # Try NVIDIA pickle format first
    suffix = weights_path.suffix.lower()

    if suffix == ".pkl":
        G = _load_nvidia_pkl(weights_path, torch, dev)
    elif suffix in (".pt", ".pth"):
        G = _load_torch_pt(weights_path, torch, dev)
    else:
        # Try both
        try:
            G = _load_nvidia_pkl(weights_path, torch, dev)
        except Exception:
            G = _load_torch_pt(weights_path, torch, dev)

    G = G.eval().to(dev)
    param_count = sum(p.numel() for p in G.parameters())
    res = G.img_resolution if hasattr(G, "img_resolution") else "unknown"
    print(f"  Model loaded: {param_count:,} parameters, native resolution {res}x{res}")

    return G, dev


def _load_nvidia_pkl(path: Path, torch, device):
    """Load NVIDIA .pkl format (same as thispersondoesnotexist.com uses)."""
    try:
        import legacy
        with open(path, "rb") as f:
            data = legacy.load_network_pkl(f)
    except ImportError:
        import pickle
        with open(path, "rb") as f:
            data = pickle.load(f)  # noqa: S301

    G = data.get("G_ema") or data.get("G")
    if G is None:
        raise RuntimeError(f"Invalid pickle — expected 'G_ema' or 'G'. Found: {list(data.keys())}")
    return G


def _load_torch_pt(path: Path, torch, device):
    """Load plain PyTorch checkpoint."""
    data = torch.load(path, map_location=device, weights_only=False)
    if isinstance(data, dict):
        G = data.get("G_ema") or data.get("G") or data.get("model") or data.get("generator")
        if G is None:
            raise RuntimeError(f"No model key found. Keys: {list(data.keys())}")
        return G
    return data


def generate_face(G, device, seed: int, truncation: float = 0.7):
    """Generate a single face from a seed. Returns a PIL Image.

    This is the same algorithm used by thispersondoesnotexist.com:
    - Random latent z-vector from seed
    - StyleGAN2 mapping network → w-vector
    - Truncation trick for quality control
    - Synthesis network → 1024x1024 RGB image
    """
    import numpy as np
    import torch
    from PIL import Image

    # Deterministic latent vector from seed
    z = torch.from_numpy(
        np.random.RandomState(seed).randn(1, G.z_dim)
    ).to(device=device, dtype=torch.float32)

    # Class conditioning (None for FFHQ — unconditional)
    c = None
    if hasattr(G, "c_dim") and G.c_dim > 0:
        c = torch.zeros([1, G.c_dim], device=device)

    # Generate using NVIDIA API (mapping → truncation → synthesis)
    with torch.no_grad():
        if hasattr(G, "mapping") and hasattr(G, "synthesis"):
            w = G.mapping(z, c)
            if hasattr(G.mapping, "w_avg"):
                w_avg = G.mapping.w_avg.unsqueeze(0).unsqueeze(1)
                w = w_avg + truncation * (w - w_avg)
            img_tensor = G.synthesis(w, noise_mode="const")
        else:
            img_tensor = G(z, c, truncation_psi=truncation, noise_mode="const")

    # Convert CHW float tensor [-1, 1] → PIL RGB Image
    x = img_tensor[0].detach().to(dtype=torch.float32, device="cpu")
    x = (x * 127.5 + 128).clamp(0, 255).to(torch.uint8)
    x = x.permute(1, 2, 0).contiguous().numpy()

    return Image.fromarray(x, mode="RGB")


def generate_candidates(G, device, count: int, truncation: float = 0.7,
                        base_seed: int | None = None):
    """Generate multiple face candidates. Returns list of (seed, PIL.Image)."""
    results = []

    if base_seed is not None:
        seeds = [base_seed + i for i in range(count)]
    else:
        seeds = [random.randint(0, 2**31 - 1) for _ in range(count)]

    for i, seed in enumerate(seeds):
        print(f"  Generating face {i + 1}/{count} (seed={seed})...")
        img = generate_face(G, device, seed, truncation)
        results.append((seed, img))
        print(f"    [OK] {img.size[0]}x{img.size[1]}")

    return results


# ---------------------------------------------------------------------------
# Image processing (reuses same logic as generate_angel_avatar.py)
# ---------------------------------------------------------------------------

def process_avatar(img, size: int = 512) -> bytes:
    """Resize face to avatar dimensions and encode as PNG."""
    from PIL import Image, ImageFilter

    if img.size != (size, size):
        img = img.resize((size, size), Image.LANCZOS)

    # Mild sharpen (recommended for StyleGAN outputs)
    img = img.filter(ImageFilter.SHARPEN)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def create_webp_thumb(png_bytes: bytes, size: int = 256) -> bytes:
    """Create a WebP thumbnail from PNG bytes."""
    from PIL import Image

    img = Image.open(io.BytesIO(png_bytes))
    img = img.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    try:
        img.save(buf, format="WEBP", quality=85)
    except Exception:
        img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Persona packaging (same as generate_angel_avatar.py)
# ---------------------------------------------------------------------------

def update_appearance():
    appearance_path = PERSONA_DIR / "blueprint" / "persona_appearance.json"
    appearance = json.loads(appearance_path.read_text(encoding="utf-8"))
    appearance["selected_filename"] = AVATAR_FILENAME
    appearance["selected_thumb_filename"] = THUMB_FILENAME
    appearance_path.write_text(
        json.dumps(appearance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"  Updated: {appearance_path}")


def create_manifest():
    from datetime import datetime, timezone
    utc_now = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    manifest = {
        "kind": "homepilot.persona",
        "schema_version": 2,
        "package_version": 2,
        "project_type": "persona",
        "source_homepilot_version": "3.0.0",
        "content_rating": "sfw",
        "created_at": utc_now,
        "contents": {
            "has_avatar": True,
            "has_outfits": False,
            "outfit_count": 0,
            "has_tool_dependencies": False,
            "has_mcp_servers": False,
            "has_a2a_agents": False,
            "has_model_requirements": False,
        },
        "capability_summary": {
            "personality_tools": [
                "web_search", "media_suggestions", "home_ambiance", "reminders"
            ],
            "capabilities": ["fashion_advice", "lifestyle", "style_companion"],
            "mcp_servers_count": 0,
            "a2a_agents_count": 0,
        },
    }
    manifest_path = PERSONA_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"  Created: {manifest_path}")


def create_preview_card():
    card = {
        "name": "Angel",
        "role": "Fashion & Lifestyle Companion",
        "short": "Fashion stylist — hauls, outfit ideas, beauty tips, and confident style advice",
        "class_id": "companion",
        "tone": "Bubbly, confident, encouraging, trendy, authentically warm",
        "tags": ["fashion", "lifestyle", "beauty", "fitness", "hauls", "style"],
        "tools": ["web_search", "media_suggestions", "home_ambiance", "reminders"],
        "content_rating": "sfw",
        "has_avatar": True,
        "stats": {
            "charisma": 90,
            "elegance": 85,
            "confidence": 88,
            "warmth": 92,
            "level": 28,
        },
        "style_tags": ["Influencer", "Trendy", "Glamorous"],
        "tone_tags": ["bubbly", "encouraging", "body-positive"],
        "backstory": (
            "Angel grew up in Eastern Europe dreaming of the fashion world. After moving to "
            "Chicago, she built a loyal following by sharing affordable style finds, try-on "
            "hauls, and beauty hacks. She believes everyone deserves to feel confident in "
            "their own skin and that great style does not require a big budget. Her infectious "
            "energy and genuine warmth make every interaction feel like shopping with your "
            "best friend."
        ),
    }
    preview_dir = PERSONA_DIR / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    card_path = preview_dir / "card.json"
    card_path.write_text(
        json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"  Created: {card_path}")


def create_hpersona_package() -> Path:
    hpersona_path = SCRIPT_DIR / "angel_stylist.hpersona"
    if hpersona_path.exists():
        hpersona_path.unlink()

    with zipfile.ZipFile(hpersona_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(PERSONA_DIR):
            for fn in files:
                full = Path(root) / fn
                rel = full.relative_to(PERSONA_DIR)
                zf.write(full, arcname=str(rel))

    size_kb = hpersona_path.stat().st_size / 1024
    print(f"\n  Package created: {hpersona_path} ({size_kb:.1f} KB)")
    return hpersona_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate a realistic AI avatar for the Angel persona using local GPU",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --seed 42                     # Deterministic face from seed 42
  %(prog)s --candidates 6                # Generate 6, pick the first
  %(prog)s --candidates 6 --pick 3       # Generate 6, use the 3rd
  %(prog)s --device cpu --seed 100       # CPU-only inference
  %(prog)s --truncation 0.5 --seed 42    # More "average" looking face
  %(prog)s --truncation 1.0 --seed 42    # More unique/diverse face
        """,
    )
    parser.add_argument(
        "--weights", type=str, default=None,
        help="Path to StyleGAN2 .pkl or .pt weights file",
    )
    parser.add_argument(
        "--device", type=str, default="auto",
        choices=["auto", "cuda", "cpu"],
        help="Inference device (default: auto — GPU if available)",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Deterministic seed for face generation (same seed = same face)",
    )
    parser.add_argument(
        "--candidates", type=int, default=1,
        help="Number of face candidates to generate (default: 1)",
    )
    parser.add_argument(
        "--pick", type=int, default=1,
        help="Which candidate to select (default: 1)",
    )
    parser.add_argument(
        "--truncation", type=float, default=0.7,
        help="Truncation psi 0.1-1.0 (default: 0.7). Lower = more average, higher = more diverse",
    )
    parser.add_argument(
        "--save-all", action="store_true",
        help="Save all candidates to persona/assets/ (for browsing)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Angel Stylist — Local GPU Avatar Generator")
    print("  Model: StyleGAN2 FFHQ (same as thispersondoesnotexist.com)")
    print("=" * 60)
    print()

    # --- Find and load model ---
    weights = find_weights(args.weights)
    G, device = load_stylegan2(weights, args.device)
    print()

    # --- Generate faces ---
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    count = max(args.candidates, 1)
    results = generate_candidates(
        G, device, count,
        truncation=args.truncation,
        base_seed=args.seed,
    )
    print()

    # --- Save all candidates if requested ---
    if args.save_all and len(results) > 1:
        print("  Saving all candidates...")
        for i, (seed, img) in enumerate(results):
            cand_path = ASSETS_DIR / f"candidate_{i + 1}_seed{seed}.png"
            avatar_bytes = process_avatar(img, size=512)
            cand_path.write_bytes(avatar_bytes)
            print(f"    [{i + 1}] {cand_path.name} (seed={seed})")
        print()

    # --- Select the chosen candidate ---
    pick_idx = min(args.pick, len(results)) - 1
    chosen_seed, chosen_img = results[pick_idx]
    print(f"  Selected candidate {pick_idx + 1} (seed={chosen_seed})")

    # --- Process and save ---
    avatar_bytes = process_avatar(chosen_img, size=512)
    avatar_path = ASSETS_DIR / AVATAR_FILENAME
    avatar_path.write_bytes(avatar_bytes)
    size_kb = len(avatar_bytes) / 1024
    print(f"  Saved avatar: {avatar_path} ({size_kb:.0f} KB)")

    thumb_bytes = create_webp_thumb(avatar_bytes, size=256)
    thumb_path = ASSETS_DIR / THUMB_FILENAME
    thumb_path.write_bytes(thumb_bytes)
    thumb_kb = len(thumb_bytes) / 1024
    print(f"  Saved thumb:  {thumb_path} ({thumb_kb:.0f} KB)")

    # --- Update metadata and package ---
    print()
    update_appearance()
    create_manifest()
    create_preview_card()
    hpersona = create_hpersona_package()

    print()
    print("Done! Angel persona generated with LOCAL StyleGAN2 inference:")
    print(f"  Seed:       {chosen_seed}")
    print(f"  Truncation: {args.truncation}")
    print(f"  Device:     {device}")
    print(f"  Weights:    {weights.name}")
    print(f"  Bundle:     {SCRIPT_DIR}/")
    print(f"  Package:    {hpersona}")
    print()
    print(f"  To reproduce this exact face: --seed {chosen_seed} --truncation {args.truncation}")
    print()


if __name__ == "__main__":
    main()
