"""
restore_avatars.py — additive recovery script for orphaned avatar /
image assets that exist on disk but aren't tracked in ``file_assets``.

Use case
--------
The user lost their persona projects (the entries in
``projects_metadata.json`` were wiped) but the underlying image
files are still on disk in ``UPLOAD_DIR``. This script walks the
upload directory, finds image files that aren't registered in the
``file_assets`` table, and registers them under the admin user so
they're owned and can be re-attached to new persona projects.

Behaviour
---------
- Idempotent. Running twice is safe — the script skips files
  already present in ``file_assets`` (matched by ``rel_path``).
- Conservative. Only image MIME types are touched. Other files
  (PDFs, text, etc.) are left alone.
- ``--dry-run`` prints what would be done without writing anything.
- Reports a summary: scanned N, already-registered M, restored K,
  errors E.

Invocation
----------
    python -m app.scripts.restore_avatars [--dry-run] [--user <id>]

When ``--user`` is omitted the script falls back to the admin
account (``get_or_create_default_user``). When no users exist at
all, ``admin`` is auto-created — matches the rest of HomePilot's
single-user bootstrap.
"""
from __future__ import annotations

import argparse
import mimetypes
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Allow running as ``python backend/app/scripts/restore_avatars.py``
# from anywhere by anchoring on the package root.
_HERE = Path(__file__).resolve()
_BACKEND_ROOT = _HERE.parents[2]  # .../backend
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _iter_image_files(root: Path) -> List[Path]:
    """Yield every image file under ``root``. Skips dotfiles and
    obvious non-asset directories. Recursive — picks up
    users/<id>/projects/<pid>/* layouts as well as flat uploads."""
    out: List[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.name.startswith("."):
            continue
        if p.suffix.lower() not in _IMAGE_EXTS:
            continue
        out.append(p)
    return out


def _existing_rel_paths(con) -> set:
    """All rel_paths already in file_assets — for dedupe."""
    rows = con.execute("SELECT rel_path FROM file_assets").fetchall()
    return {str(r[0]) for r in rows if r[0]}


def _resolve_admin_user_id(explicit: Optional[str]) -> str:
    """Pick the user to assign orphan avatars to. ``explicit`` wins;
    else the admin / default user (created on demand)."""
    from app.users import (
        ensure_users_tables,
        get_or_create_default_user,
        list_users,
    )
    ensure_users_tables()
    if explicit:
        for u in list_users():
            if u.get("id") == explicit or u.get("username") == explicit:
                return str(u["id"])
        raise SystemExit(f"--user '{explicit}' not found in users table")
    admin = get_or_create_default_user()
    return str(admin["id"])


def restore(dry_run: bool, user_id_override: Optional[str]) -> Dict[str, int]:
    """Walk UPLOAD_DIR, register orphan images under the chosen user.

    Returns a counters dict: ``{'scanned', 'already_registered',
    'restored', 'errors'}``."""
    from app.config import UPLOAD_DIR
    from app.files import insert_asset
    from app.storage import _get_db_path  # internal — same connection target

    upload_root = Path(UPLOAD_DIR)
    if not upload_root.is_dir():
        raise SystemExit(f"UPLOAD_DIR does not exist: {upload_root}")

    admin_id = _resolve_admin_user_id(user_id_override)

    import sqlite3
    con = sqlite3.connect(_get_db_path())
    try:
        con.row_factory = sqlite3.Row
        existing = _existing_rel_paths(con)
    finally:
        con.close()

    counters = {"scanned": 0, "already_registered": 0, "restored": 0, "errors": 0}
    for path in _iter_image_files(upload_root):
        counters["scanned"] += 1
        try:
            rel = str(path.relative_to(upload_root))
        except ValueError:
            counters["errors"] += 1
            continue

        if rel in existing:
            counters["already_registered"] += 1
            continue

        mime, _ = mimetypes.guess_type(str(path))
        size = path.stat().st_size

        if dry_run:
            print(f"[DRY] would register rel_path={rel!r} "
                  f"mime={mime or '?'} size={size}")
            counters["restored"] += 1
            continue

        try:
            asset_id = insert_asset(
                user_id=admin_id,
                kind="image",
                rel_path=rel,
                mime=mime or "image/png",
                size_bytes=size,
                original_name=path.name,
            )
            print(f"  + restored {rel}  ({asset_id}, {size} bytes)")
            counters["restored"] += 1
        except Exception as exc:  # noqa: BLE001 — best-effort batch
            print(f"  ! error on {rel}: {exc}")
            counters["errors"] += 1

    return counters


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be done without writing to file_assets.",
    )
    parser.add_argument(
        "--user", default=None,
        help="Target user id or username. Defaults to the admin / "
             "default user.",
    )
    args = parser.parse_args()

    print(f"[restore-avatars] mode={'DRY-RUN' if args.dry_run else 'WRITE'} "
          f"target={'admin (default)' if not args.user else args.user}")
    counters = restore(dry_run=args.dry_run, user_id_override=args.user)
    print()
    print("─" * 60)
    print(f"Scanned:             {counters['scanned']}")
    print(f"Already registered:  {counters['already_registered']}")
    print(f"Restored:            {counters['restored']}")
    print(f"Errors:              {counters['errors']}")
    print("─" * 60)
    if args.dry_run and counters["restored"]:
        print("Re-run without --dry-run to actually register the files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
