#!/usr/bin/env python3
"""
generate_persona_portrait.py — Standard portrait generator for community personas
=================================================================================

ONE tool, persona-agnostic, that produces the **standard HomePilot community
portrait** for any shared persona bundle and repacks the ``.hpersona``:

    assets/avatar_<prefix>.png        512x512  PNG   (square, center-cropped)
    assets/thumb_avatar_<prefix>.webp 256x256  WebP  (gallery thumbnail)

Faces are **fully synthetic** — no real person is ever depicted.

Source priority (matches the house standard — see
docs/PERSONA_PORTRAIT_STANDARD.md):

  1. PRIMARY  — our custom local generator (NVIDIA StyleGAN2-FFHQ, offline,
     deterministic by seed). Auto-used when a sibling ``generate_*_avatar_local.py``
     exists next to the bundle, or when ``--source local`` is forced.
  2. FALLBACK — the thispersondoesnotexist.com API (StyleGAN2, keyless, works
     everywhere — CI, containers, and the Claude Code sandbox).

Typical use (sandbox / CI — fallback path, always works):

    python generate_persona_portrait.py \
        --bundle community/shared/bundles/nexus_secretary \
        --prefix nexus --candidates 6 --contact-sheet /tmp/sheet.png
    # view the sheet, then commit the chosen candidate:
    python generate_persona_portrait.py \
        --bundle community/shared/bundles/nexus_secretary \
        --prefix nexus --use-file /tmp/persona_faces/candidate_1.jpg

Maintainer use (primary path — local StyleGAN2, deterministic):

    python generate_persona_portrait.py \
        --bundle community/shared/bundles/nexus_secretary \
        --prefix nexus --source local --seed 42

Requires Pillow (``pip install Pillow``). In the sandbox pypi.org is reachable
directly, so ``pip install Pillow`` just works.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

FACE_GEN_URL = "https://thispersondoesnotexist.com/random-person.jpeg"
USER_AGENT = "HomePilot-PersonaGenerator/2.0"
AVATAR_SIZE = 512
THUMB_SIZE = 256


# ---------------------------------------------------------------------------
# Pillow bootstrap (pypi is reachable directly in the sandbox)
# ---------------------------------------------------------------------------

def ensure_pillow():
    try:
        import PIL  # noqa: F401
        return
    except ImportError:
        print("  [setup] Pillow not found — installing (pip install Pillow) ...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "Pillow"], check=True)


# ---------------------------------------------------------------------------
# FALLBACK source — thispersondoesnotexist.com
# ---------------------------------------------------------------------------

def download_face(dst: Path, retries: int = 3) -> bool:
    """Download one synthetic 1024x1024 face. Returns True on success."""
    for attempt in range(retries):
        try:
            req = Request(FACE_GEN_URL, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=25) as resp:
                data = resp.read()
            if len(data) < 10_000:
                print(f"    [warn] response too small ({len(data)}B), retrying...")
                continue
            dst.write_bytes(data)
            return True
        except Exception as e:  # noqa: BLE001
            wait = 2 ** attempt
            print(f"    [warn] download failed ({e}); retry in {wait}s")
            time.sleep(wait)
    return False


def download_candidates(count: int, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i in range(1, count + 1):
        p = out_dir / f"candidate_{i}.jpg"
        print(f"  downloading candidate {i}/{count} ...")
        if download_face(p):
            print(f"    [ok] {p.name} ({p.stat().st_size // 1024} KB)")
            paths.append(p)
        if i < count:
            time.sleep(1)  # be polite
    return paths


# ---------------------------------------------------------------------------
# PRIMARY source — our custom local generator (best-effort, graceful fallback)
# ---------------------------------------------------------------------------

def try_local_generator(bundle: Path, prefix: str, seed: int | None) -> bool:
    """
    Run a sibling local StyleGAN2 generator if one exists
    (``generate_<prefix>_avatar_local.py`` or any ``generate_*_avatar_local.py``
    next to the bundle). Returns True if it ran and produced the avatar.

    Kept intentionally thin: the heavy StyleGAN2 inference lives in the
    avatar-service / per-persona local scripts. This just prefers them when
    present, and lets the caller fall back to the web source otherwise.
    """
    candidates = list(bundle.glob(f"generate_{prefix}_avatar_local.py")) or \
        list(bundle.glob("generate_*_avatar_local.py"))
    if not candidates:
        print("  [local] no sibling local generator found — will use fallback source")
        return False
    script = candidates[0]
    cmd = [sys.executable, str(script)]
    if seed is not None:
        cmd += ["--seed", str(seed)]
    else:
        cmd += ["--candidates", "1", "--pick", "1"]
    print(f"  [local] running custom generator: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  [local] custom generator failed ({e}) — falling back")
        return False


# ---------------------------------------------------------------------------
# Image processing — the STANDARD (512 PNG + 256 WebP, square center-crop)
# ---------------------------------------------------------------------------

def process_to_avatar(src: Path, size: int = AVATAR_SIZE) -> bytes:
    from PIL import Image
    img = Image.open(src).convert("RGB")
    w, h = img.size
    if w != h:  # center-crop to square
        side = min(w, h)
        img = img.crop(((w - side) // 2, (h - side) // 2,
                        (w - side) // 2 + side, (h - side) // 2 + side))
    img = img.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def make_thumb(png_bytes: bytes, size: int = THUMB_SIZE) -> bytes:
    from PIL import Image
    img = Image.open(io.BytesIO(png_bytes)).resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=88, method=6)
    return buf.getvalue()


def build_contact_sheet(candidates: list[Path], out: Path, cols: int = 3, cell: int = 300):
    """Montage of candidates so an AI/human reviewer can pick visually."""
    from PIL import Image, ImageDraw
    rows = (len(candidates) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * cell + 30), "white")
    d = ImageDraw.Draw(sheet)
    for idx, path in enumerate(candidates):
        im = Image.open(path).convert("RGB").resize((cell, cell))
        x, y = (idx % cols) * cell, (idx // cols) * cell + 30
        sheet.paste(im, (x, y))
        d.text((x + 6, y + 6), path.stem, fill="red")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"  [sheet] contact sheet → {out}  (open it, then re-run with --use-file)")


# ---------------------------------------------------------------------------
# Bundle wiring
# ---------------------------------------------------------------------------

def update_appearance(persona_dir: Path, avatar: str, thumb: str):
    p = persona_dir / "blueprint" / "persona_appearance.json"
    if not p.exists():
        print(f"  [skip] no appearance file at {p}")
        return
    data = json.loads(p.read_text(encoding="utf-8"))
    data["selected_filename"] = avatar
    data["selected_thumb_filename"] = thumb
    data["avatar_synthetic"] = True
    data.setdefault("avatar_source", "StyleGAN2 (local) or thispersondoesnotexist.com — depicts no real person")
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  [meta] updated {p}")


def set_has_avatar(persona_dir: Path):
    p = persona_dir / "manifest.json"
    if not p.exists():
        return
    data = json.loads(p.read_text(encoding="utf-8"))
    data.setdefault("contents", {})["has_avatar"] = True
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  [meta] has_avatar=true in {p}")


def repack_hpersona(bundle: Path, persona_dir: Path, prefix: str, flat: bool) -> Path:
    out = bundle / f"{bundle.name}.hpersona"
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(persona_dir):
            for fn in files:
                full = Path(root) / fn
                rel = full.relative_to(persona_dir if flat else persona_dir.parent)
                zf.write(full, arcname=str(rel))
    print(f"  [pack] {out} ({out.stat().st_size // 1024} KB, "
          f"{'flat' if flat else 'persona/ wrapped'})")
    return out


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Generate the standard community persona portrait.")
    ap.add_argument("--bundle", required=True, help="Bundle root (contains persona/).")
    ap.add_argument("--prefix", required=True, help="Filename stem, e.g. 'nexus' → avatar_nexus.png.")
    ap.add_argument("--source", choices=["auto", "local", "web"], default="auto",
                    help="auto: local generator then web fallback (default).")
    ap.add_argument("--candidates", type=int, default=1, help="How many web faces to fetch.")
    ap.add_argument("--pick", type=int, default=1, help="Which candidate to use (1-based).")
    ap.add_argument("--use-file", help="Use a pre-selected image instead of fetching.")
    ap.add_argument("--seed", type=int, default=None, help="Deterministic seed for local generator.")
    ap.add_argument("--contact-sheet", help="Write a montage of candidates here and STOP (no repack).")
    ap.add_argument("--flat", action="store_true",
                    help="Zip files at archive root instead of under persona/ (default: persona/).")
    ap.add_argument("--no-repack", action="store_true", help="Skip rebuilding the .hpersona.")
    args = ap.parse_args()

    ensure_pillow()

    bundle = Path(args.bundle).resolve()
    persona_dir = bundle / "persona"
    if not persona_dir.exists():
        sys.exit(f"[error] no persona/ dir under {bundle}")
    assets = persona_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    avatar_name = f"avatar_{args.prefix}.png"
    thumb_name = f"thumb_avatar_{args.prefix}.webp"
    avatar_path = assets / avatar_name
    thumb_path = assets / thumb_name

    print("=" * 68)
    print(f"  HomePilot portrait standard — {bundle.name}")
    print("=" * 68)

    # ── PRIMARY: custom local generator (source=local, or auto+available) ──
    if args.source in ("local", "auto") and not args.use_file:
        if try_local_generator(bundle, args.prefix, args.seed):
            # The local script writes+repacks itself; just normalize metadata.
            update_appearance(persona_dir, avatar_name, thumb_name)
            set_has_avatar(persona_dir)
            print("\n  Done (local generator).")
            return
        if args.source == "local":
            sys.exit("  [error] --source local requested but no working local generator. "
                     "Install weights: python avatar-service/scripts/download_models.py --model ffhq-1024")

    # ── Choose the source image ──
    if args.use_file:
        chosen = Path(args.use_file)
        if not chosen.exists():
            sys.exit(f"[error] --use-file not found: {chosen}")
        print(f"  using pre-selected face: {chosen}")
    else:
        faces_dir = Path("/tmp/persona_faces")
        cands = download_candidates(args.candidates, faces_dir)
        if not cands:
            sys.exit("[error] could not fetch any faces (offline?). "
                     "Use --source local, or pass --use-file.")
        if args.contact_sheet:
            build_contact_sheet(cands, Path(args.contact_sheet))
            return  # human/AI picks, then re-run with --use-file
        chosen = cands[min(args.pick, len(cands)) - 1]
        print(f"  selected: {chosen.name}")

    # ── Process to the STANDARD and wire into the bundle ──
    avatar_bytes = process_to_avatar(chosen)
    avatar_path.write_bytes(avatar_bytes)
    print(f"  [img] {avatar_path} ({len(avatar_bytes)//1024} KB, {AVATAR_SIZE}x{AVATAR_SIZE})")

    thumb_bytes = make_thumb(avatar_bytes)
    thumb_path.write_bytes(thumb_bytes)
    print(f"  [img] {thumb_path} ({len(thumb_bytes)//1024} KB, {THUMB_SIZE}x{THUMB_SIZE})")

    update_appearance(persona_dir, avatar_name, thumb_name)
    set_has_avatar(persona_dir)

    if not args.no_repack:
        repack_hpersona(bundle, persona_dir, args.prefix, args.flat)

    print("\n  Done. Verify the PNG before committing (open it, or read it in Claude Code).")


if __name__ == "__main__":
    main()
