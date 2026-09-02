#!/usr/bin/env python3
"""
repair-addon-avatars.py — give every addon persona its own synthetic face.

Some packages in community/addons/ ship an initials/gradient PNG instead of a
face: the avatar builder's last-resort fallback fired during export and still
wrote "srgan" metadata.  ``manifest.contents.has_avatar`` is true on every one
of them, so metadata cannot be used to find them.  This script detects them by
colour complexity, regenerates a synthetic face, and repacks the .hpersona in
place.

Also repairs duplicates: two personas sharing one face is not "their own photo".

Faces are fully synthetic (StyleGAN2) — no real person is depicted.

Usage:
    python community/scripts/repair-addon-avatars.py --pack chata --dry-run
    python community/scripts/repair-addon-avatars.py --pack chata
    python community/scripts/repair-addon-avatars.py --pack chata --only ronin_zero
    python community/scripts/repair-addon-avatars.py --pack chata --force
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ADDONS_DIR = REPO_ROOT / "community" / "addons"

# Reuse the house-standard portrait helpers (512 PNG + 256 WebP, correct
# thispersondoesnotexist endpoint, retries) instead of reimplementing them.
sys.path.insert(0, str(REPO_ROOT / "community" / "shared" / "scripts"))
from generate_persona_portrait import (  # noqa: E402
    download_face,
    ensure_pillow,
    make_thumb,
    process_to_avatar,
)

# Measured on community/addons/chata: placeholders land at 381-755 unique
# colours, real StyleGAN faces at 77,869-125,924.  The threshold sits in a
# 100x gap, so it needs no tuning.
PLACEHOLDER_MAX_COLORS = 5_000


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def unique_colors(png_bytes: bytes) -> int:
    from PIL import Image
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    return len(img.getcolors(maxcolors=1 << 24))


def diagnose(png_bytes: bytes, pid: str, seen: dict[str, str]) -> str | None:
    """Return a reason string if this avatar needs regenerating, else None.

    ``seen`` maps avatar digest → the persona that owns that face.  A persona
    that owns its digest keeps it; any later persona sharing it is a duplicate.
    """
    n = unique_colors(png_bytes)
    if n < PLACEHOLDER_MAX_COLORS:
        return f"placeholder ({n:,} colours)"
    owner = seen.get(hashlib.sha256(png_bytes).hexdigest())
    if owner is not None and owner != pid:
        return f"duplicate of {owner}"
    return None


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------

def new_face(tmp_dir: Path, pid: str) -> bytes:
    """Fetch one synthetic face and return it as a 512x512 PNG."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    raw = tmp_dir / f"{pid}.jpg"
    if not download_face(raw):
        raise RuntimeError(f"could not fetch a face for {pid}")
    return process_to_avatar(raw)


def repair_package(path: Path, seen: dict[str, str], tmp_dir: Path,
                   force: bool, dry_run: bool) -> str:
    """Repair one .hpersona in place.  Returns a status string."""
    pid = path.stem
    avatar_name = f"assets/avatar_{pid}.png"
    thumb_name = f"assets/thumb_avatar_{pid}.webp"

    with zipfile.ZipFile(path) as z:
        members = {n: z.read(n) for n in z.namelist()}

    if avatar_name not in members:
        return f"SKIP  {pid:22s} no {avatar_name}"

    reason = "forced" if force else diagnose(members[avatar_name], pid, seen)
    if not reason:
        return f"ok    {pid:22s} keeps its face"

    if dry_run:
        return f"WOULD {pid:22s} regenerate — {reason}"

    avatar = new_face(tmp_dir, pid)
    thumb = make_thumb(avatar)

    members[avatar_name] = avatar
    members[thumb_name] = thumb
    # preview.webp is what sync-addons.py publishes as the gallery image and is
    # a copy of the thumb in every shipped package.  Fixing only assets/ leaves
    # the old placeholder on the gallery card.
    if "preview.webp" in members:
        members["preview.webp"] = thumb

    # manifest.json — has_avatar was already true, keep it true and honest.
    if "manifest.json" in members:
        manifest = json.loads(members["manifest.json"])
        manifest.setdefault("contents", {})["has_avatar"] = True
        members["manifest.json"] = (
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")

    # blueprint/persona_appearance.json — record what actually produced it.
    app_name = "blueprint/persona_appearance.json"
    if app_name in members:
        app = json.loads(members[app_name])
        app["selected_filename"] = f"avatar_{pid}.png"
        app["selected_thumb_filename"] = f"thumb_avatar_{pid}.webp"
        app["avatar_synthetic"] = True
        app["avatar_source"] = (
            "StyleGAN2 (thispersondoesnotexist.com) — depicts no real person"
        )
        members[app_name] = (
            json.dumps(app, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)

    seen[hashlib.sha256(avatar).hexdigest()] = pid
    return f"FIXED {pid:22s} {reason} → {unique_colors(avatar):,} colours"


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pack", required=True, help="Pack folder under community/addons/")
    ap.add_argument("--only", action="append", default=[],
                    help="Repair only these persona ids (repeatable).")
    ap.add_argument("--force", action="store_true",
                    help="Regenerate every avatar, not just the broken ones.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would change and exit without writing.")
    args = ap.parse_args()

    ensure_pillow()

    pack_dir = ADDONS_DIR / args.pack
    if not pack_dir.is_dir():
        print(f"error: no such pack: {pack_dir}", file=sys.stderr)
        return 1

    packages = sorted(pack_dir.glob("*.hpersona"))
    if args.only:
        packages = [p for p in packages if p.stem in args.only]
    if not packages:
        print("error: no .hpersona files matched", file=sys.stderr)
        return 1

    print(f"{'=' * 64}\n  Avatar repair — {args.pack} ({len(packages)} packages)"
          f"{'  [dry run]' if args.dry_run else ''}\n{'=' * 64}")

    tmp_dir = Path("/tmp/persona_faces")
    seen: dict[str, str] = {}
    fixed = 0

    # Two passes: bank the good faces first so a duplicate is always attributed
    # to the persona that keeps it, not to whichever sorted first.
    for path in packages:
        with zipfile.ZipFile(path) as z:
            name = f"assets/avatar_{path.stem}.png"
            if name not in z.namelist():
                continue
            png = z.read(name)
        if not args.force and unique_colors(png) >= PLACEHOLDER_MAX_COLORS:
            digest = hashlib.sha256(png).hexdigest()
            seen.setdefault(digest, path.stem)

    for path in packages:
        line = repair_package(path, seen, tmp_dir, args.force, args.dry_run)
        print("  " + line)
        if line.startswith(("FIXED", "WOULD")):
            fixed += 1

    verb = "would be repaired" if args.dry_run else "repaired"
    print(f"\n  {fixed}/{len(packages)} {verb}")
    if fixed and not args.dry_run:
        print("  Next: python community/scripts/sync-addons.py   (hashes changed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
