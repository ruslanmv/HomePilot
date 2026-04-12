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
"""

import json
import os
import shutil
import sys
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


def main():
    if len(sys.argv) < 3:
        print("Usage: auto_import_personas.py <personas_dir> <data_dir>")
        sys.exit(1)

    personas_dir = Path(sys.argv[1])
    data_dir = Path(sys.argv[2])

    if not personas_dir.exists():
        print(f"Personas directory not found: {personas_dir}")
        sys.exit(0)

    hpersona_files = sorted(personas_dir.glob("*.hpersona"))
    if not hpersona_files:
        print("No .hpersona files found")
        sys.exit(0)

    print(f"  Found {len(hpersona_files)} persona files")

    imported = []
    for f in hpersona_files:
        pid = extract_persona(f, data_dir)
        if pid:
            imported.append(pid)

    # Write import manifest
    manifest_path = data_dir / "personas" / "_chata_import.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({
        "source": "chata-addon",
        "imported": imported,
        "count": len(imported),
    }, indent=2))

    print(f"  Imported {len(imported)}/{len(hpersona_files)} personas")


if __name__ == "__main__":
    main()
