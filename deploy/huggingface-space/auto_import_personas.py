"""
Auto-import .hpersona files into HomePilot's data directory.

.hpersona files are ZIP archives containing:
  manifest.json
  blueprint/persona_agent.json
  blueprint/persona_appearance.json
  assets/avatar.png (optional)
  ...

This script extracts each .hpersona into a persona directory under
the HomePilot data path so they're available immediately on startup.

Usage:
  auto_import_personas.py <personas_dir> <data_dir> [<extra_dir> ...]

Sources:
  - Positional arguments: one or more directories scanned for *.hpersona.
  - ``EXTRA_PERSONAS_DIRS`` env var: colon- or comma-separated extra dirs.
  - ``SHARED_PERSONAS_URL`` env var (optional): URL of a tarball or ZIP of
    extra .hpersona files (e.g. pointing at the HomePilot gallery pack).

The script is additive and idempotent: previously installed personas are
left untouched; new ones are added alongside.
"""

import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def extract_persona(hpersona_path: Path, data_dir: Path) -> str | None:
    """Extract a .hpersona ZIP into data_dir/personas/{persona_id}/."""
    if not zipfile.is_zipfile(hpersona_path):
        print(f"  SKIP {hpersona_path.name} (not a ZIP)")
        return None

    # Derive persona ID from filename (e.g. "chillbro_regular.hpersona" → "chillbro_regular")
    persona_id = hpersona_path.stem

    persona_dir = data_dir / "personas" / persona_id
    if persona_dir.exists():
        print(f"  SKIP {persona_id} (already exists)")
        return persona_id

    persona_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(hpersona_path, "r") as zf:
            zf.extractall(persona_dir)

        # Read manifest to get display info
        manifest_path = persona_dir / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            kind = manifest.get("kind", "unknown")
            print(f"  ✓ {persona_id} ({kind})")
        else:
            print(f"  ✓ {persona_id} (no manifest)")

        return persona_id

    except Exception as e:
        print(f"  ERROR {persona_id}: {e}")
        # Clean up failed extraction
        shutil.rmtree(persona_dir, ignore_errors=True)
        return None


def import_from_directory(src: Path, data_dir: Path, label: str) -> list[str]:
    """Import every .hpersona found directly under ``src`` (non-recursive)."""
    if not src.exists():
        print(f"  ({label}) skipped — {src} not found")
        return []
    hpersona_files = sorted(src.glob("*.hpersona"))
    if not hpersona_files:
        print(f"  ({label}) no .hpersona files in {src}")
        return []
    print(f"  ({label}) found {len(hpersona_files)} persona files in {src}")
    imported: list[str] = []
    for f in hpersona_files:
        pid = extract_persona(f, data_dir)
        if pid:
            imported.append(pid)
    return imported


def download_and_extract(url: str, dst_root: Path) -> Path | None:
    """Download a tarball or ZIP of personas and extract it to a temp dir.

    Returns the directory that should be scanned for .hpersona files, or
    ``None`` if the download failed. The caller is responsible for the
    temp lifetime (tied to the process).
    """
    try:
        print(f"  Downloading shared personas from {url}")
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = resp.read()
    except Exception as e:
        print(f"  WARNING: download failed — {e}")
        return None

    out = dst_root / "_downloaded"
    out.mkdir(parents=True, exist_ok=True)
    blob = out / "pack.bin"
    blob.write_bytes(data)

    try:
        if tarfile.is_tarfile(blob):
            with tarfile.open(blob) as tf:
                tf.extractall(out)
        elif zipfile.is_zipfile(blob):
            with zipfile.ZipFile(blob) as zf:
                zf.extractall(out)
        else:
            print("  WARNING: downloaded file is not a ZIP or TAR archive")
            return None
    except Exception as e:
        print(f"  WARNING: extraction failed — {e}")
        return None
    finally:
        blob.unlink(missing_ok=True)
    return out


def _split_env_list(value: str | None) -> list[str]:
    if not value:
        return []
    # Accept both ':' and ',' as separators for flexibility.
    raw = value.replace(":", ",")
    return [p.strip() for p in raw.split(",") if p.strip()]


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: auto_import_personas.py <personas_dir> <data_dir> [<extra_dir> ...]")
        return 1

    data_dir = Path(sys.argv[2])
    sources: list[Path] = [Path(sys.argv[1])]
    sources.extend(Path(p) for p in sys.argv[3:])
    sources.extend(Path(p) for p in _split_env_list(os.environ.get("EXTRA_PERSONAS_DIRS")))

    # De-duplicate while preserving order.
    seen: set[str] = set()
    ordered_sources: list[Path] = []
    for p in sources:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            ordered_sources.append(p)

    all_imported: list[str] = []
    total_found = 0
    for idx, src in enumerate(ordered_sources):
        label = f"source {idx + 1}"
        imported = import_from_directory(src, data_dir, label)
        all_imported.extend(imported)
        total_found += len(list(src.glob("*.hpersona"))) if src.exists() else 0

    # Optional remote shared pack.
    shared_url = os.environ.get("SHARED_PERSONAS_URL")
    if shared_url:
        tmp_root = Path(tempfile.mkdtemp(prefix="hpersona_download_"))
        downloaded = download_and_extract(shared_url, tmp_root)
        if downloaded is not None:
            # Some packs put .hpersona at the top level, others nest them — try
            # both flat and one-level-deep scanning.
            imported = import_from_directory(downloaded, data_dir, "shared-pack")
            if not imported:
                for nested in sorted(downloaded.iterdir()):
                    if nested.is_dir():
                        imported = import_from_directory(
                            nested, data_dir, f"shared-pack/{nested.name}"
                        )
                        all_imported.extend(imported)
            all_imported.extend(imported)

    # Write a consolidated import manifest (additive — include all).
    manifest_path = data_dir / "personas" / "_chata_import.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "source": "chata-addon",
                "sources_scanned": [str(p) for p in ordered_sources],
                "shared_url": shared_url or None,
                "imported": sorted(set(all_imported)),
                "count": len(set(all_imported)),
            },
            indent=2,
        )
    )

    unique = len(set(all_imported))
    print(f"  Imported {unique} unique personas across {len(ordered_sources)} source(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
