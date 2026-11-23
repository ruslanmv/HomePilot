"""Durable storage — where HomePilot's canonical data lives, backup and restore.

HomePilot owns the user's conversations, personas, projects, memories and
generated media. This module answers two operational questions:

* **Is that data on durable storage?** (:func:`describe`) — a data root under
  ``/tmp`` is erased whenever the host restarts, and the app says so plainly
  instead of looking healthy.
* **How is it backed up and restored?** (:func:`create_backup`,
  :func:`restore_backup`) — a consistent SQLite snapshot (online backup API,
  safe while the app is running) plus the upload and output files, in one
  archive under ``<data root>/backups``.

The storage backend stays configurable through the existing settings
(``DATA_DIR`` / ``SQLITE_PATH`` / ``UPLOAD_DIR`` / ``OUTPUT_DIR``). Moving to
external PostgreSQL and object storage later replaces what those point at; the
backup archive layout (``db/``, ``uploads/``, ``outputs/``, ``manifest.json``)
is the export format for that migration.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

ARCHIVE_PREFIX = "homepilot-backup-"
MANIFEST = "manifest.json"
FORMAT_VERSION = 1


def _paths() -> dict[str, Path]:
    from . import config
    from .storage import _get_db_path
    db = Path(_get_db_path())
    root = os.getenv("HOMEPILOT_DATA_ROOT") or os.getenv("DATA_DIR") or str(db.parent.parent
                                                                           if db.parent.name == "data"
                                                                           else db.parent)
    return {
        "root": Path(root),
        "db": db,
        "uploads": Path(config.UPLOAD_DIR),
        "outputs": Path(config.OUTPUT_DIR),
    }


def _is_ephemeral(path: Path) -> bool:
    explicit = (os.getenv("HOMEPILOT_STORAGE_DURABLE") or "").strip().lower()
    if explicit in ("true", "1", "yes"):
        return False
    if explicit in ("false", "0", "no"):
        return True
    resolved = str(path.resolve())
    return resolved == tempfile.gettempdir() or resolved.startswith(("/tmp/", "/var/tmp/", "/dev/shm/"))


def describe() -> dict[str, Any]:
    """Storage facts for the readiness report and the ecosystem status."""
    p = _paths()
    ephemeral = _is_ephemeral(p["db"])
    backups = list_backups()
    return {
        "data_root": str(p["root"]),
        "database": str(p["db"]),
        "durable": not ephemeral,
        "writable": os.access(p["db"].parent if p["db"].parent.exists() else p["root"], os.W_OK),
        "backups": len(backups),
        "last_backup_at": backups[0]["created_at"] if backups else None,
        "warning": (
            "Data is on temporary storage and will be erased when the host restarts. "
            "Mount a persistent volume and set DATA_DIR (on a Hugging Face Space, attach "
            "persistent storage — it mounts at /data)."
        ) if ephemeral else None,
    }


def backup_dir() -> Path:
    return _paths()["root"] / "backups"


def list_backups() -> list[dict[str, Any]]:
    directory = backup_dir()
    if not directory.is_dir():
        return []
    rows = []
    for item in directory.glob(f"{ARCHIVE_PREFIX}*.tar.gz"):
        stat = item.stat()
        rows.append({"path": str(item), "name": item.name, "bytes": stat.st_size,
                     "created_at": stat.st_mtime})
    return sorted(rows, key=lambda r: r["created_at"], reverse=True)


def create_backup(*, keep: int = 7, include_media: bool = True,
                  dest: Optional[Path] = None) -> Path:
    """Write one archive and prune old ones. Safe while the app is running."""
    p = _paths()
    target_dir = Path(dest) if dest else backup_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    archive = target_dir / f"{ARCHIVE_PREFIX}{stamp}.tar.gz"
    with tempfile.TemporaryDirectory(dir=target_dir) as work:
        snapshot = Path(work) / "homepilot.db"
        if p["db"].exists():
            src = sqlite3.connect(str(p["db"]))
            dst = sqlite3.connect(str(snapshot))
            try:
                src.backup(dst)            # consistent even with writers active
            finally:
                dst.close()
                src.close()
        manifest = {
            "format": FORMAT_VERSION,
            "created_at": time.time(),
            "database": snapshot.exists(),
            "include_media": include_media,
            "source": {k: str(v) for k, v in p.items()},
        }
        (Path(work) / MANIFEST).write_text(json.dumps(manifest, indent=2))
        partial = archive.with_suffix(".partial")
        with tarfile.open(partial, "w:gz") as tar:
            tar.add(Path(work) / MANIFEST, arcname=MANIFEST)
            if snapshot.exists():
                tar.add(snapshot, arcname="db/homepilot.db")
            if include_media:
                for name in ("uploads", "outputs"):
                    if p[name].is_dir():
                        tar.add(p[name], arcname=name)
        partial.replace(archive)           # never leave a half-written archive
    if keep > 0 and dest is None:
        for old in list_backups()[keep:]:
            try:
                os.remove(old["path"])
            except OSError:
                pass
    return archive


def _safe_members(tar: tarfile.TarFile):
    for member in tar.getmembers():
        name = member.name
        if name.startswith(("/", "..")) or ".." in Path(name).parts:
            raise ValueError(f"unsafe path in archive: {name}")
        if member.issym() or member.islnk():
            raise ValueError(f"links are not allowed in a backup archive: {name}")
        yield member


def restore_backup(archive: Path, *, force: bool = False) -> dict[str, Any]:
    """Restore an archive into the configured data locations.

    Refuses to overwrite an existing database unless ``force`` is set; with
    ``force`` the current database is first moved aside (``.pre-restore``), so
    a restore can itself be undone. Run with the app stopped.
    """
    p = _paths()
    archive = Path(archive)
    if not archive.is_file():
        raise FileNotFoundError(str(archive))
    if p["db"].exists() and not force:
        raise FileExistsError(
            f"{p['db']} already exists. Pass force=True (--force) to replace it; "
            "the current database is kept beside it as .pre-restore.")
    with tempfile.TemporaryDirectory() as work:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(work, members=_safe_members(tar))
        manifest = json.loads((Path(work) / MANIFEST).read_text())
        if manifest.get("format") != FORMAT_VERSION:
            raise ValueError(f"unsupported backup format: {manifest.get('format')}")
        restored: list[str] = []
        snapshot = Path(work) / "db" / "homepilot.db"
        if snapshot.exists():
            p["db"].parent.mkdir(parents=True, exist_ok=True)
            if p["db"].exists():
                shutil.move(str(p["db"]), str(p["db"]) + ".pre-restore")
            shutil.copy2(snapshot, p["db"])
            restored.append("database")
        for name in ("uploads", "outputs"):
            src = Path(work) / name
            if src.is_dir():
                p[name].mkdir(parents=True, exist_ok=True)
                shutil.copytree(src, p[name], dirs_exist_ok=True)
                restored.append(name)
    return {"restored": restored, "from": str(archive), "created_at": manifest.get("created_at")}


# ── command line: ``python -m app.durable_storage backup|restore|list|status`` ──

def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Back up or restore HomePilot data.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("list")
    b = sub.add_parser("backup")
    b.add_argument("--keep", type=int, default=7)
    b.add_argument("--no-media", action="store_true")
    b.add_argument("--dest", type=Path, default=None)
    b.add_argument("--if-older-than", type=float, default=None, metavar="HOURS")
    r = sub.add_parser("restore")
    r.add_argument("archive", type=Path)
    r.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "status":
        print(json.dumps(describe(), indent=2))
    elif args.cmd == "list":
        print(json.dumps(list_backups(), indent=2))
    elif args.cmd == "backup":
        if args.if_older_than is not None:
            existing = list_backups()
            if existing and time.time() - existing[0]["created_at"] < args.if_older_than * 3600:
                print(f"skip: latest backup is newer than {args.if_older_than}h")
                return 0
        print(create_backup(keep=args.keep, include_media=not args.no_media, dest=args.dest))
    elif args.cmd == "restore":
        print(json.dumps(restore_backup(args.archive, force=args.force), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
