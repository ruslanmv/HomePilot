#!/usr/bin/env python3
"""
sync-addons.py — Merge addon persona packs into the gallery registry.

Reads community/sample/registry.json (HomePilot native personas) and
community/addons/*/pack.json + *.hpersona files, then builds a merged
registry.json ready for R2 upload.

Usage:
    python community/scripts/sync-addons.py [--upload]

    --upload    Also upload packages/previews/registry to R2 via AWS CLI.
                Requires: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
                R2_ENDPOINT, R2_BUCKET env vars.

Without --upload, it only builds /tmp/gallery-registry.json for inspection.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Paths ────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLE_REGISTRY = REPO_ROOT / "community" / "sample" / "registry.json"
ADDONS_DIR = REPO_ROOT / "community" / "addons"
OUTPUT_REGISTRY = Path("/tmp/gallery-registry.json")

# ── Avatar quality gate ──────────────────────────────────
#
# Fourteen Chata personas shipped with gradient-and-initials tiles instead of faces:
# the avatar builder's last-resort fallback fired during export and still wrote
# "srgan" provenance. Every one of them declared `contents.has_avatar: true`, and
# every file it names was present and the right size — so neither the metadata nor a
# file-presence check could tell a face from a failure. Only the pixels could.
#
# Measured on those packages: placeholders carry 381-755 unique colours, real
# StyleGAN faces 77,869-125,924. The threshold sits in a 100x gap and needs no tuning.
PLACEHOLDER_MAX_COLORS = 5_000


def _unique_colors(png_bytes: bytes) -> int:
    from PIL import Image  # noqa: PLC0415 — optional at import, required at use

    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    return len(img.getcolors(maxcolors=1 << 24))


def check_avatar(z: zipfile.ZipFile, names: set[str], pid: str,
                 avatar_seen: dict[str, str] | None) -> str | None:
    """Return a rejection reason for this package's avatar, or None if it is fine.

    Two failures, both invisible to metadata:

    * a placeholder, found by colour complexity;
    * a face already published under another persona's name in this same run —
      five Chata personas shared one byte-identical avatar, which reads to a user
      as a copy-paste mistake rather than the caching bug it was.
    """
    avatar_name = f"assets/avatar_{pid}.png"
    if avatar_name not in names:
        return None  # nothing claimed, nothing to check

    data = z.read(avatar_name)

    try:
        colors = _unique_colors(data)
    except ImportError:
        # Loud, and fatal. Skipping the check quietly is precisely the shape of the
        # bug this gate exists to catch: something failed, nothing said so, and a
        # broken package sailed through looking exactly like a good one.
        print("  ERROR Pillow is not installed — the avatar quality gate cannot run.",
              file=sys.stderr)
        print("        Install it (pip install Pillow) or the registry is unchecked.",
              file=sys.stderr)
        raise SystemExit(2) from None

    if colors < PLACEHOLDER_MAX_COLORS:
        return f"placeholder avatar ({colors:,} unique colours)"

    if avatar_seen is not None:
        digest = hashlib.sha256(data).hexdigest()
        owner = avatar_seen.get(digest)
        if owner is not None and owner != pid:
            return f"avatar is byte-identical to {owner}"
        avatar_seen[digest] = pid

    return None


# ── Extract metadata from .hpersona ──────────────────────

def extract_persona_meta(hpersona_path: Path, pack: dict,
                         avatar_seen: dict[str, str] | None = None) -> dict[str, Any] | None:
    """Extract a registry entry from a .hpersona ZIP file."""
    pid = hpersona_path.stem
    if not zipfile.is_zipfile(hpersona_path):
        print(f"  SKIP {pid} (not a ZIP)")
        return None

    file_bytes = hpersona_path.read_bytes()
    sha256 = hashlib.sha256(file_bytes).hexdigest()
    size_bytes = len(file_bytes)

    with zipfile.ZipFile(hpersona_path) as z:
        names = set(z.namelist())

        # manifest
        if "manifest.json" not in names:
            print(f"  SKIP {pid} (no manifest)")
            return None
        manifest = json.loads(z.read("manifest.json"))

        # agent
        agent = {}
        if "blueprint/persona_agent.json" in names:
            agent = json.loads(z.read("blueprint/persona_agent.json"))

        # card
        card = {}
        if "preview/card.json" in names:
            card = json.loads(z.read("preview/card.json"))

        # Refuse to publish a broken avatar rather than putting it in front of users.
        rejection = check_avatar(z, names, pid, avatar_seen)
        if rejection:
            print(f"  SKIP {pid} ({rejection})")
            return None

    # Build entry
    name = card.get("name") or agent.get("label") or pid.replace("_", " ").title()
    short = card.get("short") or agent.get("role", "")
    tags = list(set(card.get("tags", []) + pack.get("default_tags", [])))
    # A persona's own rating wins. The pack rating is only a default for legacy
    # packages that do not declare one — ORing the two meant a single wrong word in
    # pack.json branded all 14 Chata personas NSFW while every manifest said "sfw",
    # and no persona could ever correct it.
    content_rating = manifest.get("content_rating") or pack.get("content_rating") or "sfw"
    nsfw = content_rating in {"nsfw", "adult"}
    has_avatar = manifest.get("contents", {}).get("has_avatar", False)
    pack_id = pack.get("id", "")

    version = "1.0.0"

    return {
        "id": pid,
        "name": name,
        "short": short,
        "tags": tags,
        "nsfw": nsfw,
        "author": pack.get("author", "Community"),
        "collection": pack_id,
        "pack": pack_id,
        "class_id": card.get("class_id") or pack.get("default_class_id", "companion"),
        "has_avatar": has_avatar,
        "downloads": 0,
        "latest": {
            "version": version,
            "package_url": f"packages/{pid}/{version}/persona.hpersona",
            "preview_url": f"previews/{pid}/{version}/preview.webp",
            "card_url": f"previews/{pid}/{version}/card.json",
            "sha256": sha256,
            "size_bytes": size_bytes,
        },
    }


def extract_preview(hpersona_path: Path, output_dir: Path) -> None:
    """Extract preview.webp and card.json from a .hpersona for R2 upload."""
    pid = hpersona_path.stem
    version = "1.0.0"
    dest = output_dir / "previews" / pid / version
    dest.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(hpersona_path) as z:
        # Preview image
        for candidate in ["preview.webp", "preview.png"]:
            if candidate in z.namelist():
                (dest / "preview.webp").write_bytes(z.read(candidate))
                break
        else:
            # Fallback: use thumbnail from assets
            for name in z.namelist():
                if name.startswith("assets/thumb_") and name.endswith(".webp"):
                    (dest / "preview.webp").write_bytes(z.read(name))
                    break

        # Card
        if "preview/card.json" in z.namelist():
            (dest / "card.json").write_bytes(z.read("preview/card.json"))

    # Copy package
    pkg_dest = output_dir / "packages" / pid / version
    pkg_dest.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(hpersona_path, pkg_dest / "persona.hpersona")


# ── Main ─────────────────────────────────────────────────

def main():
    do_upload = "--upload" in sys.argv

    print("=" * 60)
    print("  HomePilot Gallery — Addon Sync")
    print("=" * 60)

    # 1. Load base registry (HomePilot native personas)
    if SAMPLE_REGISTRY.exists():
        base = json.loads(SAMPLE_REGISTRY.read_text())
        base_items = {item["id"]: item for item in base.get("items", [])}
        print(f"\n[base] {len(base_items)} native personas from sample/registry.json")
    else:
        base_items = {}
        print("\n[base] No sample/registry.json found — starting fresh")

    # 2. Scan addons
    addon_dirs = sorted(
        d for d in ADDONS_DIR.iterdir()
        if d.is_dir() and (d / "pack.json").exists()
    ) if ADDONS_DIR.exists() else []

    print(f"[addons] Found {len(addon_dirs)} addon packs: {[d.name for d in addon_dirs]}")

    upload_dir = Path("/tmp/gallery-upload")
    upload_dir.mkdir(parents=True, exist_ok=True)

    addon_count = 0
    # Shared across the whole run, not per pack: two personas in different packs
    # wearing one face is the same problem as two in the same one.
    avatar_seen: dict[str, str] = {}
    for addon_dir in addon_dirs:
        pack = json.loads((addon_dir / "pack.json").read_text())
        pack_id = pack["id"]
        hpersona_files = sorted(addon_dir.glob("*.hpersona"))

        print(f"\n[{pack_id}] {pack['name']} — {len(hpersona_files)} personas")

        for hp in hpersona_files:
            entry = extract_persona_meta(hp, pack, avatar_seen)
            if entry:
                # Preserve download count from existing entries
                if entry["id"] in base_items:
                    entry["downloads"] = base_items[entry["id"]].get("downloads", 0)
                base_items[entry["id"]] = entry
                addon_count += 1
                print(f"  + {entry['id']:30s} nsfw={entry['nsfw']}  tags={entry['tags']}")

                if do_upload:
                    extract_preview(hp, upload_dir)

    # 3. Build merged registry
    registry = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": list(base_items.values()),
        "total": len(base_items),
        "filtered": len(base_items),
        "configured": True,
    }

    OUTPUT_REGISTRY.write_text(json.dumps(registry, indent=2, ensure_ascii=False))

    sfw = sum(1 for i in registry["items"] if not i.get("nsfw"))
    nsfw = sum(1 for i in registry["items"] if i.get("nsfw"))
    print(f"\n[registry] {len(registry['items'])} total ({sfw} SFW, {nsfw} NSFW)")
    print(f"[registry] Written to {OUTPUT_REGISTRY}")

    # 4. Upload to R2 (if --upload)
    if do_upload:
        r2_endpoint = os.environ.get("R2_ENDPOINT", "")
        r2_bucket = os.environ.get("R2_BUCKET", "homepilot")

        if not r2_endpoint:
            print("\n[upload] R2_ENDPOINT not set — skipping upload")
            return

        print(f"\n[upload] Uploading to s3://{r2_bucket}/ ...")

        # Upload registry
        _s3_cp(OUTPUT_REGISTRY, f"s3://{r2_bucket}/registry/registry.json",
               "application/json", r2_endpoint)

        # Upload packages + previews
        for item in registry["items"]:
            pid = item["id"]
            ver = item["latest"]["version"]

            pkg = upload_dir / "packages" / pid / ver / "persona.hpersona"
            if pkg.exists():
                _s3_cp(pkg, f"s3://{r2_bucket}/packages/{pid}/{ver}/persona.hpersona",
                       "application/octet-stream", r2_endpoint)

            preview = upload_dir / "previews" / pid / ver / "preview.webp"
            if preview.exists():
                _s3_cp(preview, f"s3://{r2_bucket}/previews/{pid}/{ver}/preview.webp",
                       "image/webp", r2_endpoint)

            card = upload_dir / "previews" / pid / ver / "card.json"
            if card.exists():
                _s3_cp(card, f"s3://{r2_bucket}/previews/{pid}/{ver}/card.json",
                       "application/json", r2_endpoint)

        print(f"[upload] Done — {addon_count} addon personas uploaded")

    print(f"\n{'=' * 60}")
    print(f"  Sync complete: {len(registry['items'])} personas in registry")
    print(f"  SFW: {sfw}  |  NSFW: {nsfw}  |  Addons: {addon_count}")
    print(f"{'=' * 60}")


def _s3_cp(local: Path, s3_path: str, content_type: str, endpoint: str):
    """Upload a file to R2 via AWS CLI."""
    result = subprocess.run(
        ["aws", "s3", "cp", str(local), s3_path,
         "--endpoint-url", endpoint,
         "--content-type", content_type,
         "--quiet"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  WARN: upload failed for {s3_path}: {result.stderr[:100]}")


if __name__ == "__main__":
    main()
