"""
Operations on HomePilot's media (docs/design/MEDIA_STORAGE.md, Phases 3 and 4):

    python -m app.media_ops verify              every asset is where its row says, hashes match
    python -m app.media_ops migrate [--to s3]   copy assets into the configured backend, verify, flip the row
    python -m app.media_ops backup  <dir>       database copy + every asset's bytes + a manifest
    python -m app.media_ops restore <dir>       put a backup's assets into the configured backend
    python -m app.media_ops gc                  remove what has been in the trash longer than the retention

Nothing here deletes a source during a migration unless ``--prune-source`` says so, and a
copy is only recorded after it has been read back and its SHA-256 matched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

from . import media_storage as _ms
from .media_storage import LocalStorage, MediaStorage
from .storage import _get_db_path, ensure_file_assets_columns


def get_storage() -> MediaStorage:
    """Looked up on the module each time, so a configured (or test-substituted) backend is seen."""
    return _ms.get_storage()


def storage_named(name: str) -> Optional[MediaStorage]:
    return _ms.storage_named(name)

_CHUNK = 1024 * 1024
Log = Callable[[str], None]

ROW_COLUMNS = ("id", "user_id", "kind", "rel_path", "mime", "size_bytes", "original_name", "project_id",
               "conversation_id", "storage_backend", "sha256", "visibility", "created_at")


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_get_db_path())
    con.row_factory = sqlite3.Row
    ensure_file_assets_columns(con)
    return con


def _rows(con: sqlite3.Connection, where: str = "deleted_at IS NULL", params: tuple = ()) -> List[sqlite3.Row]:
    return con.execute(f"SELECT {', '.join(ROW_COLUMNS)}, deleted_at FROM file_assets WHERE {where} ORDER BY created_at",
                       params).fetchall()


def sha256_of(stream) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = stream.read(_CHUNK)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def copy_hashed(src: MediaStorage, dst: MediaStorage, key: str) -> str:
    """Copy one object, hashing it on the way; the SHA-256 of what was read."""
    digest = hashlib.sha256()
    with src.open(key) as reader, dst.open_write(key) as writer:
        while True:
            chunk = reader.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            writer.write(chunk)
    return digest.hexdigest()


def read_back_hash(storage: MediaStorage, key: str) -> str:
    with storage.open(key) as reader:
        return sha256_of(reader)


# ── verify ─────────────────────────────────────────────────────────────────────


def verify(log: Log = print) -> Dict[str, int]:
    """Every live asset: its backend configured, the object there, the hash as recorded."""
    counts = {"ok": 0, "missing": 0, "mismatch": 0, "unconfigured": 0, "unhashed": 0}
    con = _db()
    try:
        for row in _rows(con):
            store = storage_named(row["storage_backend"] or "local")
            if store is None:
                counts["unconfigured"] += 1
                log(f"  ? {row['id']} {row['rel_path']}: backend {row['storage_backend']!r} is not configured")
                continue
            if not store.exists(row["rel_path"]):
                counts["missing"] += 1
                log(f"  ✗ {row['id']} {row['rel_path']}: missing from {store.name}")
                continue
            if not row["sha256"]:
                counts["unhashed"] += 1
                counts["ok"] += 1
                continue
            if read_back_hash(store, row["rel_path"]) != row["sha256"]:
                counts["mismatch"] += 1
                log(f"  ✗ {row['id']} {row['rel_path']}: SHA-256 differs from the recorded one")
                continue
            counts["ok"] += 1
    finally:
        con.close()
    log(f"verify: {counts}")
    return counts


# ── migrate ────────────────────────────────────────────────────────────────────


def migrate(target_name: Optional[str] = None, *, dry_run: bool = False, prune_source: bool = False,
            log: Log = print) -> Dict[str, int]:
    """Copy every live asset that is not in the target backend into it — read back, hash
    checked — then flip its row. Sources stay unless ``prune_source``."""
    target = get_storage() if not target_name else storage_named(target_name)
    if target is None:
        raise RuntimeError(f"target backend {target_name!r} is not configured")
    counts = {"moved": 0, "already": 0, "missing_source": 0, "unconfigured_source": 0, "failed": 0}
    con = _db()
    try:
        for row in _rows(con, "deleted_at IS NULL AND storage_backend != ?", (target.name,)):
            key, src_name = row["rel_path"], row["storage_backend"] or "local"
            src = storage_named(src_name)
            if src is None:
                counts["unconfigured_source"] += 1
                log(f"  ? {row['id']} {key}: source backend {src_name!r} is not configured")
                continue
            if not src.exists(key):
                counts["missing_source"] += 1
                log(f"  ✗ {row['id']} {key}: not in {src_name}")
                continue
            if dry_run:
                counts["moved"] += 1
                log(f"  → {row['id']} {key}: would copy {src_name} → {target.name}")
                continue
            try:
                if target.exists(key) and read_back_hash(target, key) == (row["sha256"] or read_back_hash(src, key)):
                    digest = row["sha256"] or read_back_hash(src, key)
                    counts["already"] += 1
                else:
                    digest = copy_hashed(src, target, key)
                    if read_back_hash(target, key) != digest:
                        raise RuntimeError("read-back hash differs from what was written")
                    if row["sha256"] and row["sha256"] != digest:
                        raise RuntimeError("the source no longer matches its recorded hash")
                    counts["moved"] += 1
                con.execute("UPDATE file_assets SET storage_backend = ?, sha256 = ? WHERE id = ?",
                            (target.name, digest, row["id"]))
                try:
                    con.execute("UPDATE assets SET storage_backend = ? WHERE storage_backend = ? AND storage_key = ?",
                                (target.name, src_name, key))
                except sqlite3.Error:
                    pass   # the registry row for this key already exists in the target backend
                con.commit()
                if prune_source and src is not target:
                    src.delete(key)
                log(f"  ✓ {row['id']} {key}: {src_name} → {target.name}")
            except Exception as e:
                counts["failed"] += 1
                log(f"  ✗ {row['id']} {key}: {e} — row left on {src_name}")
    finally:
        con.close()
    log(f"migrate → {target.name}{' (dry run)' if dry_run else ''}: {counts}")
    return counts


# ── backup / restore ───────────────────────────────────────────────────────────


def backup(dest: Path, log: Log = print) -> Dict[str, Any]:
    """``dest/homepilot.db`` (a consistent copy), ``dest/media/<key>`` for every live asset,
    ``dest/manifest.json``. Portable: it does not depend on any backend's on-disk format."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    media = LocalStorage(dest / "media")
    con = _db()
    try:
        db_copy = sqlite3.connect(dest / "homepilot.db")
        with db_copy:
            con.backup(db_copy)
        db_copy.close()
        manifest: Dict[str, Any] = {"created_at": datetime.now(timezone.utc).isoformat(), "assets": [], "skipped": []}
        for row in _rows(con):
            store = storage_named(row["storage_backend"] or "local")
            key = row["rel_path"]
            if store is None or not store.exists(key):
                manifest["skipped"].append({"id": row["id"], "rel_path": key, "storage_backend": row["storage_backend"]})
                log(f"  ✗ {row['id']} {key}: not available from {row['storage_backend']}")
                continue
            digest = copy_hashed(store, media, key)
            entry = {c: row[c] for c in ROW_COLUMNS}
            entry["sha256"] = digest
            manifest["assets"].append(entry)
        (dest / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    finally:
        con.close()
    log(f"backup → {dest}: {len(manifest['assets'])} assets, {len(manifest['skipped'])} skipped")
    return manifest


def restore(src: Path, target_name: Optional[str] = None, log: Log = print) -> Dict[str, int]:
    """Put a backup's assets into the configured backend (read back, hash checked) and make
    sure each has its row, naming that backend. The database file itself is restored by
    copying ``homepilot.db`` back while HomePilot is stopped — see the design doc."""
    src = Path(src)
    manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    media = LocalStorage(src / "media")
    target = get_storage() if not target_name else storage_named(target_name)
    if target is None:
        raise RuntimeError(f"target backend {target_name!r} is not configured")
    counts = {"restored": 0, "failed": 0}
    con = _db()
    try:
        for entry in manifest["assets"]:
            key = entry["rel_path"]
            try:
                digest = copy_hashed(media, target, key)
                if digest != entry.get("sha256"):
                    raise RuntimeError("the backup copy does not match its manifest hash")
                if read_back_hash(target, key) != digest:
                    raise RuntimeError("read-back hash differs from what was written")
                con.execute(
                    """INSERT INTO file_assets(id, user_id, kind, rel_path, mime, size_bytes, original_name,
                                               project_id, conversation_id, storage_backend, sha256, visibility, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET storage_backend = excluded.storage_backend,
                                                     sha256 = excluded.sha256, deleted_at = NULL""",
                    (entry["id"], entry["user_id"], entry["kind"], key, entry.get("mime") or "",
                     int(entry.get("size_bytes") or 0), entry.get("original_name") or "", entry.get("project_id") or "",
                     entry.get("conversation_id") or "", target.name, digest, entry.get("visibility") or "private",
                     entry.get("created_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
                )
                con.commit()
                counts["restored"] += 1
            except Exception as e:
                counts["failed"] += 1
                log(f"  ✗ {entry['id']} {key}: {e}")
    finally:
        con.close()
    log(f"restore ← {src} into {target.name}: {counts}")
    return counts


# ── trash ──────────────────────────────────────────────────────────────────────


def trash_retention_days() -> float:
    raw = (os.getenv("MEDIA_TRASH_RETENTION_DAYS") or "7").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 7.0


def purge_trash(retention_days: Optional[float] = None, *, now: Optional[float] = None, log: Log = print) -> Dict[str, int]:
    """Remove the bytes and rows of assets deleted longer ago than the retention. A row whose
    backend is not configured is left — the object cannot be reached, so neither goes."""
    days = trash_retention_days() if retention_days is None else float(retention_days)
    cutoff = datetime.fromtimestamp((now if now is not None else time.time()) - days * 86400, tz=timezone.utc)
    cutoff_s = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    counts = {"purged": 0, "kept": 0, "failed": 0}
    con = _db()
    try:
        rows = con.execute("SELECT id, rel_path, storage_backend FROM file_assets WHERE deleted_at IS NOT NULL AND deleted_at <= ?",
                           (cutoff_s,)).fetchall()
        for row in rows:
            store = storage_named(row["storage_backend"] or "local")
            if store is None:
                counts["kept"] += 1
                continue
            try:
                store.delete(row["rel_path"])
                con.execute("DELETE FROM file_assets WHERE id = ?", (row["id"],))
                con.commit()
                counts["purged"] += 1
            except Exception as e:
                counts["failed"] += 1
                log(f"  ✗ {row['id']} {row['rel_path']}: {e}")
    finally:
        con.close()
    if counts["purged"] or counts["failed"]:
        log(f"trash: {counts} (retention {days:g} days)")
    return counts


_gc_thread: Optional[threading.Thread] = None


def start_trash_gc(interval_s: float = 6 * 3600, first_delay_s: float = 60.0) -> None:
    """A daemon thread that purges the trash shortly after startup and every ``interval_s``."""
    global _gc_thread
    if _gc_thread and _gc_thread.is_alive():
        return

    def _loop() -> None:
        time.sleep(first_delay_s)
        while True:
            try:
                purge_trash()
            except Exception as e:  # never let housekeeping take the thread down
                print(f"[MEDIA] trash purge failed: {e}")
            time.sleep(interval_s)

    _gc_thread = threading.Thread(target=_loop, name="media-trash-gc", daemon=True)
    _gc_thread.start()


# ── CLI ────────────────────────────────────────────────────────────────────────


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.media_ops", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    p = sub.add_parser("migrate")
    p.add_argument("--to", dest="target", default=None, help="backend name (default: the configured one)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--prune-source", action="store_true", help="delete each source object after its copy verified")
    p = sub.add_parser("backup")
    p.add_argument("dest")
    p = sub.add_parser("restore")
    p.add_argument("src")
    p.add_argument("--to", dest="target", default=None)
    p = sub.add_parser("gc")
    p.add_argument("--retention-days", type=float, default=None)
    args = parser.parse_args(argv)

    if args.command == "verify":
        counts = verify()
        return 1 if counts["missing"] or counts["mismatch"] else 0
    if args.command == "migrate":
        counts = migrate(args.target, dry_run=args.dry_run, prune_source=args.prune_source)
        return 1 if counts["failed"] else 0
    if args.command == "backup":
        manifest = backup(Path(args.dest))
        return 1 if manifest["skipped"] else 0
    if args.command == "restore":
        counts = restore(Path(args.src), args.target)
        return 1 if counts["failed"] else 0
    if args.command == "gc":
        purge_trash(args.retention_days)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
