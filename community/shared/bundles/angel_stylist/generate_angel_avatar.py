#!/usr/bin/env python3
"""
generate_angel_avatar.py — Generate a realistic AI avatar for Angel persona
============================================================================

Downloads a photorealistic AI-generated face from https://thispersondoesnotexist.com
(StyleGAN2-based, free, no signup, no API key required). The site returns a unique
1024x1024 JPEG on every request — all faces are fully synthetic (no real person).

The script downloads multiple candidates and lets the user pick the best match,
or accepts a pre-selected face via --use-file. It then crops/resizes to 512x512,
generates a 256x256 WebP thumbnail, and rebuilds the .hpersona ZIP package.

Usage:
  # Interactive: download N candidates and pick the best
  python generate_angel_avatar.py --candidates 5

  # Use a specific pre-downloaded image
  python generate_angel_avatar.py --use-file /tmp/face_18.jpg

  # Quick: just grab one random face
  python generate_angel_avatar.py
"""
import io
import json
import os
import struct
import sys
import time
import zipfile
import zlib
from pathlib import Path
from urllib.request import urlopen, Request

SCRIPT_DIR = Path(__file__).resolve().parent
PERSONA_DIR = SCRIPT_DIR / "persona"
ASSETS_DIR = PERSONA_DIR / "assets"
AVATAR_FILENAME = "avatar_angel.png"
THUMB_FILENAME = "thumb_avatar_angel.webp"

FACE_GEN_URL = "https://thispersondoesnotexist.com"
USER_AGENT = "HomePilot-PersonaGenerator/1.0"


# ---------------------------------------------------------------------------
# Face download from thispersondoesnotexist.com
# ---------------------------------------------------------------------------

def download_face(output_path: Path, retries: int = 3) -> bool:
    """Download a single AI-generated face from thispersondoesnotexist.com.

    Returns True on success, False on failure.
    Each request returns a unique 1024x1024 JPEG of a non-existent person.
    """
    for attempt in range(retries):
        try:
            req = Request(FACE_GEN_URL, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=15) as resp:
                data = resp.read()
                if len(data) < 10_000:
                    print(f"    [WARN] Response too small ({len(data)} bytes), retrying...")
                    continue
                output_path.write_bytes(data)
                return True
        except Exception as e:
            wait = 2 ** attempt
            print(f"    [WARN] Download failed ({e}), retrying in {wait}s...")
            time.sleep(wait)
    return False


def download_candidates(count: int, output_dir: Path) -> list[Path]:
    """Download multiple face candidates with a 1-second delay between requests."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(1, count + 1):
        path = output_dir / f"candidate_{i}.jpg"
        print(f"  Downloading candidate {i}/{count}...")
        if download_face(path):
            size_kb = path.stat().st_size / 1024
            print(f"    [OK] {path.name} ({size_kb:.0f} KB)")
            paths.append(path)
        else:
            print(f"    [FAIL] Could not download candidate {i}")
        if i < count:
            time.sleep(1)  # Be polite to the service
    return paths


# ---------------------------------------------------------------------------
# Image processing
# ---------------------------------------------------------------------------

def process_face_to_avatar(source_path: Path, size: int = 512) -> bytes:
    """Convert a face JPEG to a cropped, resized PNG avatar.

    Attempts to use Pillow for high-quality processing.
    Falls back to raw JPEG->PNG conversion if Pillow is unavailable.
    """
    try:
        from PIL import Image

        img = Image.open(source_path)
        # The source is 1024x1024 from thispersondoesnotexist.com
        # Center-crop and resize to target size
        w, h = img.size
        # Crop to square if not already
        if w != h:
            side = min(w, h)
            left = (w - side) // 2
            top = (h - side) // 2
            img = img.crop((left, top, left + side, top + side))
        # Resize to target
        img = img.resize((size, size), Image.LANCZOS)
        # Convert to PNG
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    except ImportError:
        print("  [WARN] Pillow not available, saving raw JPEG as PNG name")
        return source_path.read_bytes()


def create_webp_thumb(png_bytes: bytes, size: int = 256) -> bytes:
    """Create a WebP thumbnail from PNG bytes."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(png_bytes))
        img = img.resize((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        try:
            img.save(buf, format="WEBP", quality=85)
        except Exception:
            img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        return png_bytes


def _create_fallback_gradient(width: int, height: int) -> bytes:
    """Pure-stdlib fallback: rose-gold gradient PNG (no Pillow, no network)."""
    def make_chunk(chunk_type: bytes, data: bytes) -> bytes:
        chunk = chunk_type + data
        return (struct.pack(">I", len(data)) + chunk +
                struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF))

    bg = (219, 172, 155)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw_rows = b""
    for y in range(height):
        ratio = y / height
        r = int(bg[0] - ratio * 30)
        g = int(bg[1] - ratio * 40)
        b = int(bg[2] - ratio * 30)
        raw_rows += b"\x00" + bytes([r, g, b]) * width
    idat = zlib.compress(raw_rows)

    png = b"\x89PNG\r\n\x1a\n"
    png += make_chunk(b"IHDR", ihdr)
    png += make_chunk(b"IDAT", idat)
    png += make_chunk(b"IEND", b"")
    return png


# ---------------------------------------------------------------------------
# Persona packaging helpers
# ---------------------------------------------------------------------------

def update_appearance():
    """Update persona_appearance.json with avatar filenames."""
    appearance_path = PERSONA_DIR / "blueprint" / "persona_appearance.json"
    appearance = json.loads(appearance_path.read_text(encoding="utf-8"))
    appearance["selected_filename"] = AVATAR_FILENAME
    appearance["selected_thumb_filename"] = THUMB_FILENAME
    appearance_path.write_text(
        json.dumps(appearance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"  Updated: {appearance_path}")


def create_manifest():
    """Create persona manifest.json."""
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
    """Create preview card for community gallery."""
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
    """Create .hpersona ZIP package from the persona directory."""
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
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate a realistic AI avatar for the Angel persona"
    )
    parser.add_argument(
        "--use-file", type=str, default=None,
        help="Path to a pre-downloaded face image to use as the avatar"
    )
    parser.add_argument(
        "--candidates", type=int, default=1,
        help="Number of face candidates to download from thispersondoesnotexist.com (default: 1)"
    )
    parser.add_argument(
        "--pick", type=int, default=1,
        help="Which candidate number to use (default: 1, the first/only one)"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Angel Stylist — Realistic Avatar Generator")
    print("  Source: https://thispersondoesnotexist.com")
    print("=" * 60)
    print()

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    avatar_path = ASSETS_DIR / AVATAR_FILENAME
    thumb_path = ASSETS_DIR / THUMB_FILENAME

    if args.use_file:
        # Use a pre-existing file
        source = Path(args.use_file)
        if not source.exists():
            print(f"  [ERROR] File not found: {source}")
            sys.exit(1)
        print(f"  Using pre-selected face: {source}")
        avatar_bytes = process_face_to_avatar(source, size=512)

    else:
        # Download from thispersondoesnotexist.com
        tmp_dir = SCRIPT_DIR / ".candidates"
        candidates = download_candidates(args.candidates, tmp_dir)

        if not candidates:
            print("  [ERROR] No faces downloaded. Using fallback gradient.")
            avatar_bytes = _create_fallback_gradient(512, 512)
            avatar_path.write_bytes(avatar_bytes)
            thumb_path.write_bytes(create_webp_thumb(avatar_bytes, 256))
        else:
            pick_idx = min(args.pick, len(candidates)) - 1
            chosen = candidates[pick_idx]
            print(f"\n  Selected: {chosen.name}")
            avatar_bytes = process_face_to_avatar(chosen, size=512)

            # Clean up candidates
            for c in candidates:
                c.unlink(missing_ok=True)
            tmp_dir.rmdir()

    # Save avatar
    avatar_path.write_bytes(avatar_bytes)
    size_kb = len(avatar_bytes) / 1024
    print(f"  Saved avatar: {avatar_path} ({size_kb:.0f} KB)")

    # Save thumbnail
    thumb_bytes = create_webp_thumb(avatar_bytes, 256)
    thumb_path.write_bytes(thumb_bytes)
    thumb_kb = len(thumb_bytes) / 1024
    print(f"  Saved thumb:  {thumb_path} ({thumb_kb:.0f} KB)")

    # Update metadata and package
    print()
    update_appearance()
    create_manifest()
    create_preview_card()
    hpersona = create_hpersona_package()

    print()
    print("Done! Angel persona is ready with realistic AI-generated avatar:")
    print(f"  Bundle:  {SCRIPT_DIR}/")
    print(f"  Package: {hpersona}")
    print()


if __name__ == "__main__":
    main()
