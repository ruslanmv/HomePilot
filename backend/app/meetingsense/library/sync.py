"""Folder sync — import finished recordings from a folder such as ``D:\\AIRecord``.

**Who may read the disk.** The server reads a folder only when it lies below a root the
operator listed in ``MEETINGS_SYNC_ALLOWED_ROOTS``. A path typed in the browser is a request,
not a grant; a backend on another machine cannot see this computer's ``D:`` at all, and is
told so rather than pretending.

When HomePilot runs under WSL (the usual Windows setup), ``D:\\AIRecord`` is
``/mnt/d/AIRecord`` to the server, and the translation is done here.

**What a scan does.** It walks the folder, groups files into meetings (the same discovery an
upload uses), and imports each meeting once its files have stopped changing — a recording
still being written is left for the next scan. Re-running a scan is always safe: an
Insta360 meeting is recognised by its ``localMeetingId`` and anything else by the SHA-256 of
its recording, so nothing is imported twice, and a renamed file is followed rather than
duplicated. Source files are only read. A file that later disappears leaves its meeting in
the library, marked "source no longer available".
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import db
from .adapters import discover
from .config import load_library_config
from .importer import analyse, ingest

log = logging.getLogger(__name__)

_loop_task: Optional[asyncio.Task] = None
_scan_lock: Optional[asyncio.Lock] = None


class SyncRefused(Exception):
    def __init__(self, message: str, *, code: str, hint: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.hint = hint


_WIN_DRIVE = re.compile(r"^([A-Za-z]):[\\/]*(.*)$")


def _is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def server_path(user_path: str) -> str:
    """Where the server finds a folder the user named. ``D:\\X`` → ``/mnt/d/X`` off Windows."""
    raw = (user_path or "").strip().strip('"')
    m = _WIN_DRIVE.match(raw)
    if m and os.name != "nt":
        rest = m.group(2).replace("\\", "/").strip("/")
        return f"/mnt/{m.group(1).lower()}/{rest}" if rest else f"/mnt/{m.group(1).lower()}"
    return raw


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def authorize(user_path: str) -> Tuple[str, Path]:
    """Validate a requested folder; return (as entered, resolved server path)."""
    cfg = load_library_config()
    if not user_path or not user_path.strip():
        raise SyncRefused("Choose a folder.", code="missing_path")
    if not cfg.sync_roots:
        raise SyncRefused(
            "Folder sync is turned off on this server.",
            code="sync_not_enabled",
            hint=("Ask the person who runs HomePilot to allow the folder: set "
                  "MEETINGS_SYNC_ALLOWED_ROOTS=" + (server_path("D:\\AIRecord") if os.name != "nt" else "D:\\AIRecord")
                  + " and restart."),
        )
    resolved = Path(server_path(user_path)).expanduser()
    try:
        resolved = resolved.resolve(strict=True)
    except (OSError, RuntimeError):
        hint = ""
        if _WIN_DRIVE.match(user_path.strip()) and os.name != "nt" and not _is_wsl():
            hint = ("This HomePilot server is not running on that Windows computer, so it cannot see its "
                    "drives. Upload the recordings instead, or run HomePilot on that computer.")
        raise SyncRefused(f"The folder {user_path!r} was not found on the HomePilot server.",
                          code="not_found", hint=hint)
    if not resolved.is_dir():
        raise SyncRefused(f"{user_path!r} is not a folder.", code="not_a_folder")
    allowed = []
    for root in cfg.sync_roots:
        try:
            allowed.append(Path(server_path(root)).expanduser().resolve())
        except (OSError, RuntimeError):
            continue
    if not any(_within(resolved, root) for root in allowed):
        raise SyncRefused(
            "That folder is outside the folders this server allows.",
            code="not_allowed",
            hint="Allowed: " + "; ".join(cfg.sync_roots),
        )
    return user_path.strip(), resolved


def add_source(user_path: str, *, display_name: str = "", owner_user_id: str = "",
               project_id: Optional[str] = None) -> Dict[str, Any]:
    entered, resolved = authorize(user_path)
    for existing in db.list_sources():
        if Path(existing["resolved_path"]) == resolved:
            return existing
    sid = db.create_source(kind="folder", display_name=display_name.strip() or Path(entered).name or entered,
                           path=entered, resolved_path=str(resolved), owner_user_id=owner_user_id,
                           project_id=project_id or None)
    return db.get_source(sid)  # type: ignore[return-value]


def _stable(source_id: str, files, *, now: float, stability_s: int) -> bool:
    """Every file of a meeting has stopped changing: not modified for ``stability_s`` seconds,
    and the same size and mtime as at the last scan (a file that changed since is still being
    written, whatever its mtime says)."""
    ok = True
    for f in files:
        seen = db.observe(source_id, f.rel, f.size, f.mtime)
        if seen.get("changed"):
            ok = False
            continue
        settled_since = min(float(seen["first_seen_at"]), float(f.mtime))
        if now - settled_since < stability_s:
            ok = False
    return ok


def scan_source(source_id: str) -> Dict[str, Any]:
    """One reconciliation pass over a folder. Idempotent; safe after a crash."""
    source = db.get_source(source_id)
    if source is None:
        raise SyncRefused("No such folder source.", code="not_found")
    cfg = load_library_config()
    now = time.time()
    counts = {"found": 0, "imported": 0, "already": 0, "waiting": 0, "skipped": 0, "failed": 0}
    errors: List[str] = []
    db.update_source(source_id, last_scan_at=now)
    try:
        _, root = authorize(source["path"])  # re-checked every scan: the operator may revoke
    except SyncRefused as exc:
        db.update_source(source_id, last_error=f"{exc} {exc.hint}".strip(), counts=counts)
        raise
    known = {a["relative_path"]: a for a in db.assets_for_source(source_id)}
    present = set()
    for cand in discover(root):
        counts["found"] += 1
        for f in cand.files:
            present.add(f.rel)
        if not cand.files:
            counts["skipped"] += 1
            continue
        # Already imported from this folder at this path (fast path, no hashing).
        prior = known.get(cand.audio.rel if cand.audio else cand.files[0].rel)
        if prior and prior.get("meeting_id"):
            counts["already"] += 1
            continue
        if not _stable(source_id, cand.files, now=now, stability_s=cfg.stability_s):
            counts["waiting"] += 1
            continue
        try:
            item = analyse(cand)
            if item.get("duplicate_of"):
                _follow_rename(item, cand, source_id)
                counts["already"] += 1
                continue
            if item.get("outcome") == "skip":
                counts["skipped"] += 1
                continue
            # Automatic attach only when exactly one scheduled meeting fits; otherwise the
            # recording becomes its own meeting and the match is offered in the library.
            attach = item.get("attach_to") if len(item.get("scheduled_matches") or []) == 1 else None
            ingest(cand, source_id=source_id, origin_type="sync", owner_user_id=source.get("owner_user_id") or "",
                   project_id=source.get("project_id"), attach_to=attach, analysed=item)
            counts["imported"] += 1
        except Exception as exc:  # noqa: BLE001 — one bad file must not stop the folder
            counts["failed"] += 1
            errors.append(f"{cand.key}: {exc}")
            log.warning("meetings sync: %s failed: %s", cand.key, exc)
    # Files that vanished: keep the meeting, say the original is gone.
    for rel, asset in known.items():
        available = 1 if rel in present else 0
        if int(asset.get("source_available") or 0) != available:
            db.update_asset(asset["id"], source_available=available)
    db.update_source(source_id, last_success_at=time.time(),
                     last_error="; ".join(errors)[:1000] if errors else "", counts=counts)
    if counts["imported"]:
        from .jobs import wake  # noqa: PLC0415

        wake()
    return counts


def _follow_rename(item: Dict[str, Any], cand, source_id: str) -> None:
    """Same recording, new path: point the asset at its new name instead of re-importing."""
    if cand.audio is None:
        return
    sha = (item.get("audio") or {}).get("sha256")
    for asset in db.assets_with_sha(sha) if sha else []:
        if asset["source_id"] == source_id and asset["relative_path"] != cand.audio.rel:
            db.update_asset(asset["id"], relative_path=cand.audio.rel, source_available=1)


async def scan_async(source_id: str) -> Dict[str, Any]:
    global _scan_lock
    if _scan_lock is None:
        _scan_lock = asyncio.Lock()
    async with _scan_lock:
        return await asyncio.to_thread(scan_source, source_id)


def start_sync_loop() -> bool:
    global _loop_task
    cfg = load_library_config()
    if not (cfg.enabled and cfg.sync_roots) or os.getenv("MEETINGS_LIBRARY_WORKER", "1").strip().lower() in ("0", "false", "off"):
        return False
    if _loop_task is not None and not _loop_task.done():
        return True
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    _loop_task = loop.create_task(_sync_loop())
    return True


async def _sync_loop() -> None:
    db.ensure_migrated()
    while True:
        interval = load_library_config().sync_interval_s
        for source in db.list_sources():
            if not source.get("enabled"):
                continue
            try:
                await scan_async(source["id"])
            except SyncRefused:
                pass  # recorded on the source; shown in Folder Sync
            except Exception:  # noqa: BLE001
                log.exception("meetings sync: scan of %s failed", source["id"])
        await asyncio.sleep(interval)


async def stop_sync_loop() -> None:
    global _loop_task
    if _loop_task is not None:
        _loop_task.cancel()
        try:
            await _loop_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    _loop_task = None
