#!/usr/bin/env python3
"""Merge the External Additive Personas pack into HomePilot's gallery
registry.json without ever deleting existing entries.

Production-safety contract:

  * The current gallery (Scarlett, Atlas, any community-submitted persona)
    is in production and used by real people. Do NOT touch its entries.
  * 'install-personas' merges every persona from the additive pack's
    registry.json into the gallery's items[], keyed by id. Existing
    entries are preserved byte-for-byte; new ids are appended; existing
    ids in the additive pack are skipped (the gallery copy wins).
  * 'uninstall-personas' removes ONLY the ids that came from the additive
    pack; it does not touch any other entry.

Usage:

    python3 scripts/merge_additive_registry.py \\
      --gallery-registry docs/registry.json \\
      --pack-registry .cache/personas/registry/registry.json

    python3 scripts/merge_additive_registry.py \\
      --gallery-registry docs/registry.json \\
      --pack-registry .cache/personas/registry/registry.json \\
      --remove
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def merge(gallery_path: Path, pack_path: Path) -> int:
    gallery = _load(gallery_path)
    pack = _load(pack_path)

    existing_ids = {item["id"] for item in gallery.get("items", [])}
    added: list[str] = []
    skipped: list[str] = []

    for item in pack.get("items", []):
        if item["id"] in existing_ids:
            skipped.append(item["id"])
            continue
        gallery.setdefault("items", []).append(item)
        added.append(item["id"])

    gallery["total"] = len(gallery.get("items", []))
    gallery["generated_at"] = _now_iso()
    gallery.setdefault("source", "github-pages")
    if "+ homepilotai/personas" not in gallery["source"]:
        gallery["source"] += " + homepilotai/personas additive pack"

    _save(gallery_path, gallery)
    print(f"merge: added {len(added)} (existing kept). new={added} skipped={skipped}")
    return 0


def remove(gallery_path: Path, pack_path: Path) -> int:
    gallery = _load(gallery_path)
    pack = _load(pack_path)

    pack_ids = {item["id"] for item in pack.get("items", [])}
    before = len(gallery.get("items", []))
    kept = [i for i in gallery.get("items", []) if i["id"] not in pack_ids]
    removed = before - len(kept)
    gallery["items"] = kept
    gallery["total"] = len(kept)
    gallery["generated_at"] = _now_iso()
    _save(gallery_path, gallery)
    print(f"uninstall: removed {removed} additive entries; {len(kept)} preserved")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="merge_additive_registry")
    parser.add_argument("--gallery-registry", required=True, type=Path)
    parser.add_argument("--pack-registry", required=True, type=Path)
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()

    if not args.gallery_registry.exists():
        print(f"gallery registry not found: {args.gallery_registry}", file=sys.stderr)
        return 2
    if not args.pack_registry.exists():
        print(f"pack registry not found: {args.pack_registry}", file=sys.stderr)
        return 2

    if args.remove:
        return remove(args.gallery_registry, args.pack_registry)
    return merge(args.gallery_registry, args.pack_registry)


if __name__ == "__main__":
    sys.exit(main())
