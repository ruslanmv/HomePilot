#!/usr/bin/env python3
"""
HomePilot recovery CLI.

Self-contained — imports only the Python stdlib + optional ``bcrypt``.
Does NOT import any ``app.*`` module so it works even when the backend
virtualenv is broken, uv is missing, or the disk is so full the
backend cannot start.

Usage
-----
    python scripts/recovery.py status
    python scripts/recovery.py backup
    python scripts/recovery.py list-users
    python scripts/recovery.py reset-password --user alice [--password s3cret]
    python scripts/recovery.py unlock-all [--password s3cret] --yes I-UNDERSTAND
    python scripts/recovery.py clear-sessions
    python scripts/recovery.py prune-uploads [--min-mb 100]

Or, preferably, via the Makefile wrappers:
    make recovery                       (prints the menu)
    make recovery-status
    make recovery-backup
    make recovery-list-users
    make recovery-reset-password USER=alice [PASSWORD=s3cret]
    make recovery-unlock-all [PASSWORD=s3cret] YES=I-UNDERSTAND
    make recovery-clear-sessions
    make recovery-prune-uploads [MIN_MB=100]

Safety invariants
-----------------
* Runs locally only. No network surface.
* Never prints password hashes.
* Always writes a timestamped copy of the DB into
  ``recovery-backups/<ts>/homepilot.db`` BEFORE any mutation.
* ``unlock-all`` refuses to run without ``--yes I-UNDERSTAND``.
* ``prune-uploads`` is listing-only. It never removes files.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import os
import secrets
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Iterable, Optional


# ----------------------------------------------------------------------------
# Path resolution
# ----------------------------------------------------------------------------
# Kept in sync with backend/app/config.py:119 and backend/app/storage.py:13.
# We intentionally do NOT import those modules — recovery must be robust to
# the backend being un-importable (bad venv, missing deps, broken file).

REPO_ROOT = Path(__file__).resolve().parent.parent


def _resolve_data_root() -> Path:
    env = os.getenv("DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (REPO_ROOT / "backend" / "data").resolve()


def _resolve_db_path() -> Path:
    env = os.getenv("SQLITE_PATH", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return _resolve_data_root() / "homepilot.db"


def _resolve_uploads_dir() -> Path:
    env = os.getenv("UPLOAD_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return _resolve_data_root() / "uploads"


def _resolve_backups_dir() -> Path:
    return (REPO_ROOT / "recovery-backups").resolve()


# ----------------------------------------------------------------------------
# Password hashing — matches backend/app/users.py:93
# ----------------------------------------------------------------------------

try:
    import bcrypt  # type: ignore
    _HAS_BCRYPT = True
except Exception:
    _HAS_BCRYPT = False


def _hash_password(password: str) -> str:
    if not password:
        return ""
    if _HAS_BCRYPT:
        return "bcrypt:" + bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    # Fallback: SHA-256 + salt. Matches users.py exactly so the backend
    # can still verify the hash on next login.
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"{salt}:{h}"


# ----------------------------------------------------------------------------
# Backup — always run before a mutation
# ----------------------------------------------------------------------------

def _snapshot_db(reason: str) -> Optional[Path]:
    """Copy the DB file to recovery-backups/<ts>/. Returns the new path."""
    db = _resolve_db_path()
    if not db.exists():
        return None
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest_dir = _resolve_backups_dir() / f"{ts}-{reason}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / db.name
    # Use the SQLite backup API when possible so an open connection
    # elsewhere doesn't corrupt the copy. Falls back to file copy.
    try:
        src = sqlite3.connect(str(db))
        dst = sqlite3.connect(str(dest))
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
    except sqlite3.Error:
        shutil.copy2(db, dest)
    return dest


# ----------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------

def _die(msg: str, code: int = 1) -> None:
    print(f"\n✗ {msg}\n", file=sys.stderr)
    sys.exit(code)


def _fmt_size(bytes_: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(bytes_)
    for u in units:
        if f < 1024.0 or u == units[-1]:
            return f"{f:.1f} {u}"
        f /= 1024.0
    return f"{f:.1f} TB"


def _dir_size(p: Path) -> int:
    if not p.exists():
        return 0
    total = 0
    for root, _, files in os.walk(p):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def cmd_status(_args: argparse.Namespace) -> int:
    db = _resolve_db_path()
    uploads = _resolve_uploads_dir()

    print("─── HomePilot recovery status ────────────────────────────────")
    print(f"  Repo root       : {REPO_ROOT}")
    print(f"  Data root       : {_resolve_data_root()}")
    print(f"  SQLite DB       : {db}")
    print(f"  Uploads dir     : {uploads}")
    print(f"  Backups dir     : {_resolve_backups_dir()}")
    print(f"  bcrypt          : {'yes' if _HAS_BCRYPT else 'no (will fall back to SHA-256+salt)'}")
    print()

    # Disk space
    try:
        du = shutil.disk_usage(str(REPO_ROOT))
        pct = (du.used / du.total) * 100
        print(f"  Disk free       : {_fmt_size(du.free)} of {_fmt_size(du.total)} ({pct:.1f}% used)")
    except OSError as e:
        print(f"  Disk free       : (unavailable: {e})")

    # DB
    if not db.exists():
        print(f"  DB              : NOT FOUND — backend never initialized on this path")
        return 0
    print(f"  DB size         : {_fmt_size(db.stat().st_size)}")
    try:
        con = sqlite3.connect(str(db))
        cur = con.cursor()
        integrity = cur.execute("PRAGMA integrity_check").fetchone()[0]
        print(f"  DB integrity    : {integrity}")
        cur.execute("SELECT COUNT(*) FROM users")
        n_users = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM user_sessions")
        n_sessions = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM users WHERE password_hash IS NOT NULL AND password_hash != ''"
        )
        n_with_pw = cur.fetchone()[0]
        con.close()
        print(f"  Users           : {n_users} ({n_with_pw} with a password)")
        print(f"  Active sessions : {n_sessions}")
    except sqlite3.Error as e:
        print(f"  DB error        : {e}")
        return 2

    # Uploads
    if uploads.exists():
        print(f"  Uploads size    : {_fmt_size(_dir_size(uploads))}")
    else:
        print(f"  Uploads dir     : not present yet")

    print("───────────────────────────────────────────────────────────────")
    return 0


def cmd_backup(_args: argparse.Namespace) -> int:
    snap = _snapshot_db("manual")
    if snap is None:
        _die("No DB found to back up.")
    print(f"✓ DB snapshotted to {snap}")
    return 0


def cmd_list_users(_args: argparse.Namespace) -> int:
    db = _resolve_db_path()
    if not db.exists():
        _die(f"No DB at {db}.")
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    try:
        cur.execute(
            "SELECT id, username, display_name, email, password_hash, "
            "onboarding_complete, created_at FROM users ORDER BY created_at"
        )
        rows = cur.fetchall()
    except sqlite3.Error as e:
        con.close()
        _die(f"DB read failed: {e}")
        return 1
    con.close()

    if not rows:
        print("  (no users in the database)")
        return 0

    # Pretty table.
    headers = ("username", "display_name", "email", "pw?", "onboarded", "id", "created_at")
    print("  " + " · ".join(headers))
    print("  " + "-" * 88)
    for r in rows:
        has_pw = "yes" if (r["password_hash"] or "") else "no"
        onboarded = "yes" if r["onboarding_complete"] else "no"
        print(
            "  {username!s:20} · {display_name!s:22} · {email!s:26} · "
            "{pw:3} · {onb:3} · {id} · {created}".format(
                username=r["username"],
                display_name=(r["display_name"] or "")[:22],
                email=(r["email"] or "")[:26],
                pw=has_pw,
                onb=onboarded,
                id=r["id"][:8],
                created=r["created_at"],
            )
        )
    return 0


def _apply_new_password(cursor: sqlite3.Cursor, user_ids: Iterable[str], new_pw: str) -> int:
    h = _hash_password(new_pw)
    n = 0
    for uid in user_ids:
        cursor.execute(
            "UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (h, uid),
        )
        n += cursor.rowcount
    return n


def _generate_temp_password() -> str:
    # 16 base36-ish chars; easy to paste but hard to brute-force.
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(16))


def cmd_reset_password(args: argparse.Namespace) -> int:
    db = _resolve_db_path()
    if not db.exists():
        _die(f"No DB at {db}.")
    user = args.user.strip()
    if not user:
        _die("--user is required.")
    new_pw = (args.password or "").strip() or _generate_temp_password()
    generated = not args.password

    snap = _snapshot_db("reset-password")
    if snap:
        print(f"  Backup saved to {snap}")

    con = sqlite3.connect(str(db))
    cur = con.cursor()
    cur.execute("SELECT id, username FROM users WHERE username = ? COLLATE NOCASE", (user,))
    row = cur.fetchone()
    if row is None:
        con.close()
        _die(f"No user named {user!r} found. Run `make recovery-list-users` to see the options.")
        return 1
    uid, username = row[0], row[1]

    n = _apply_new_password(cur, [uid], new_pw)
    # Also invalidate this user's outstanding sessions — they may be stale.
    cur.execute("DELETE FROM user_sessions WHERE user_id = ?", (uid,))
    con.commit()
    con.close()

    print(f"✓ Updated password for user {username!r} ({n} row).")
    print(f"  Existing sessions for this user were invalidated.")
    if generated:
        print()
        print(f"  ┌────────────────────────────────────────────────────────────┐")
        print(f"  │  TEMPORARY PASSWORD (shown ONCE — save it now):            │")
        print(f"  │    {new_pw:<56} │")
        print(f"  └────────────────────────────────────────────────────────────┘")
        print("  Log in, then change it from Settings → Account.")
    return 0


def cmd_unlock_all(args: argparse.Namespace) -> int:
    if (args.yes or "").strip() != "I-UNDERSTAND":
        _die(
            "unlock-all is destructive across EVERY account. Re-run with\n"
            "  --yes I-UNDERSTAND\n"
            "to confirm. A DB backup will be created first."
        )
    db = _resolve_db_path()
    if not db.exists():
        _die(f"No DB at {db}.")

    new_pw = (args.password or "").strip() or _generate_temp_password()
    generated = not args.password

    snap = _snapshot_db("unlock-all")
    if snap:
        print(f"  Backup saved to {snap}")

    con = sqlite3.connect(str(db))
    cur = con.cursor()
    cur.execute("SELECT id, username FROM users")
    users = cur.fetchall()
    if not users:
        con.close()
        _die("No users in the database. Nothing to unlock.")
        return 1
    n = _apply_new_password(cur, [u[0] for u in users], new_pw)
    cur.execute("DELETE FROM user_sessions")
    con.commit()
    con.close()

    print(f"✓ Reset password for {n} user(s); all sessions invalidated.")
    if generated:
        print()
        print(f"  ┌────────────────────────────────────────────────────────────┐")
        print(f"  │  TEMPORARY PASSWORD (same for every user — shown ONCE):    │")
        print(f"  │    {new_pw:<56} │")
        print(f"  └────────────────────────────────────────────────────────────┘")
        print("  Log in, then change it per account from Settings → Account.")
    for _uid, uname in users:
        print(f"    · {uname}")
    return 0


def cmd_clear_sessions(_args: argparse.Namespace) -> int:
    db = _resolve_db_path()
    if not db.exists():
        _die(f"No DB at {db}.")
    snap = _snapshot_db("clear-sessions")
    if snap:
        print(f"  Backup saved to {snap}")
    con = sqlite3.connect(str(db))
    cur = con.cursor()
    cur.execute("DELETE FROM user_sessions")
    n = cur.rowcount
    con.commit()
    con.close()
    print(f"✓ Invalidated {n} session(s). Every user will need to re-login.")
    return 0


def _resolve_asset_file(rel_path: str, uploads_dir: Path) -> Optional[Path]:
    """Map a file_assets.rel_path to an on-disk file. The backend stores
    rel_path either as a relative segment under UPLOAD_DIR ("users/<u>/
    images/foo.png") or, for some legacy rows, as an absolute path.
    Return whichever exists, or None."""
    if not rel_path:
        return None
    p = Path(rel_path)
    if p.is_absolute() and p.exists():
        return p
    candidate = (uploads_dir / rel_path).resolve()
    if candidate.exists():
        return candidate
    return None


def _sanitize_for_path(name: str) -> str:
    """Make a username safe to use as a directory segment."""
    import re
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", name or "unknown").strip("._-")
    return clean or "unknown"


def cmd_recover_images(args: argparse.Namespace) -> int:
    """Export every image asset for each user into
    recovery-images/<username>/, optionally zipping each one.

    Rationale: when the HDD fills up or the backend breaks, the files in
    UPLOAD_DIR are still on disk — but without the running app it's
    impossible to tell which image belongs to which account. This walks
    file_assets and produces a per-user folder (or ZIP) containing every
    image the user owns, so people can recover their own data from a
    broken install.
    """
    import shutil as _shutil
    import zipfile

    db = _resolve_db_path()
    if not db.exists():
        _die(f"No DB at {db}.")
    uploads = _resolve_uploads_dir()
    if not uploads.exists():
        print(f"  Uploads dir {uploads} does not exist — no files to recover.")
        return 0

    out_root = Path(args.out).expanduser().resolve() if args.out else (REPO_ROOT / "recovery-images").resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Resolve target users.
    where = ""
    params: tuple = ()
    if args.user:
        cur.execute(
            "SELECT id, username FROM users WHERE username = ? COLLATE NOCASE",
            (args.user.strip(),),
        )
        row = cur.fetchone()
        if row is None:
            con.close()
            _die(f"No user named {args.user!r} found. Run `make recovery-list-users`.")
            return 1
        users = [(row["id"], row["username"])]
    else:
        cur.execute("SELECT id, username FROM users ORDER BY username COLLATE NOCASE")
        users = [(r["id"], r["username"]) for r in cur.fetchall()]
    if not users:
        con.close()
        print("  No users in the database.")
        return 0

    summary: list[tuple[str, int, int, int]] = []  # (username, copied, missing, bytes)
    grand_copied = 0
    grand_missing = 0
    grand_bytes = 0

    for uid, uname in users:
        cur.execute(
            """
            SELECT id, rel_path, mime, size_bytes, original_name, project_id, created_at
              FROM file_assets
             WHERE user_id = ?
               AND (kind = 'image' OR mime LIKE 'image/%')
             ORDER BY created_at
            """,
            (uid,),
        )
        rows = cur.fetchall()
        if not rows:
            summary.append((uname, 0, 0, 0))
            continue

        safe = _sanitize_for_path(uname)
        user_dir = out_root / safe
        # Re-use the same bucket on re-run so duplicates don't explode
        # disk, but ensure the directory exists.
        user_dir.mkdir(parents=True, exist_ok=True)

        copied = 0
        missing = 0
        total_bytes = 0
        manifest_lines = [
            "# HomePilot recovery-images manifest",
            f"# username={uname}",
            f"# user_id={uid}",
            f"# generated_at={_dt.datetime.now().isoformat()}",
            "# columns: asset_id | size | original_name | rel_path | on_disk",
            "",
        ]

        zip_target: Optional[zipfile.ZipFile] = None
        if args.zip:
            zip_path = out_root / f"{safe}.zip"
            zip_target = zipfile.ZipFile(
                str(zip_path), "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True,
            )

        for r in rows:
            src = _resolve_asset_file(r["rel_path"] or "", uploads)
            original = r["original_name"] or Path(r["rel_path"] or "").name or f"{r['id']}.bin"
            if src is None:
                missing += 1
                manifest_lines.append(
                    f"MISSING | {r['id']} | {r['size_bytes']} | {original} | {r['rel_path']} | (not on disk)"
                )
                continue
            # Namespace the file in the output by asset id so we never
            # collide when two images share an original_name.
            out_name = f"{r['id'][:12]}__{original}"
            if zip_target is not None:
                zip_target.write(str(src), arcname=out_name)
            else:
                dst = user_dir / out_name
                if not dst.exists():
                    _shutil.copy2(src, dst)
            copied += 1
            total_bytes += (r["size_bytes"] or src.stat().st_size)
            manifest_lines.append(
                f"OK      | {r['id']} | {r['size_bytes']} | {original} | {r['rel_path']} | {src}"
            )

        if zip_target is not None:
            # Stash the manifest inside the zip too.
            zip_target.writestr(
                "MANIFEST.txt", "\n".join(manifest_lines) + "\n",
            )
            zip_target.close()
        else:
            (user_dir / "MANIFEST.txt").write_text(
                "\n".join(manifest_lines) + "\n", encoding="utf-8",
            )
        summary.append((uname, copied, missing, total_bytes))
        grand_copied += copied
        grand_missing += missing
        grand_bytes += total_bytes

    con.close()

    print(f"  Output:  {out_root}")
    print(f"  Users:   {len(users)}")
    print(f"  Files:   {grand_copied} recovered, {grand_missing} missing-on-disk")
    print(f"  Bytes:   {_fmt_size(grand_bytes)}")
    print()
    print(f"  {'username':<24} {'images':>8} {'missing':>8} {'size':>12}")
    print(f"  {'-' * 24} {'-' * 8} {'-' * 8} {'-' * 12}")
    for uname, copied, missing, nbytes in summary:
        print(f"  {uname:<24} {copied:>8} {missing:>8} {_fmt_size(nbytes):>12}")
    return 0


def cmd_prune_uploads(args: argparse.Namespace) -> int:
    uploads = _resolve_uploads_dir()
    if not uploads.exists():
        print(f"  Uploads dir {uploads} does not exist. Nothing to list.")
        return 0
    min_bytes = int(max(1, args.min_mb)) * 1024 * 1024
    big: list[tuple[int, Path]] = []
    for root, _, files in os.walk(uploads):
        for name in files:
            p = Path(root) / name
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            if sz >= min_bytes:
                big.append((sz, p))
    if not big:
        print(f"  No files ≥ {args.min_mb} MB under {uploads}.")
        return 0
    big.sort(key=lambda x: x[0], reverse=True)
    total = sum(s for s, _ in big)
    print(f"  {len(big)} file(s) ≥ {args.min_mb} MB — total {_fmt_size(total)}:\n")
    for sz, p in big[:200]:
        print(f"    {_fmt_size(sz):>10}  {p}")
    if len(big) > 200:
        print(f"    … and {len(big) - 200} more. Re-run with --min-mb {args.min_mb * 2} to narrow.")
    print()
    print("  To delete a specific file:     rm '<path>'")
    print("  This command never deletes anything automatically.")
    return 0


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="homepilot-recovery",
        description="Emergency recovery for HomePilot user accounts + local DB.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Disk + DB + users + sessions snapshot.")
    sub.add_parser("backup", help="Manual DB backup into recovery-backups/.")
    sub.add_parser("list-users", help="Show every user in the database.")

    r = sub.add_parser(
        "reset-password",
        help="Set a new password for a single user. Auto-backs up the DB first.",
    )
    r.add_argument("--user", required=True, help="username to recover")
    r.add_argument("--password", default="", help="new password (default: random 16-char)")

    u = sub.add_parser(
        "unlock-all",
        help="Reset the password for EVERY user. Requires --yes I-UNDERSTAND.",
    )
    u.add_argument("--password", default="", help="shared new password (default: random 16-char)")
    u.add_argument("--yes", default="", help="type I-UNDERSTAND to confirm")

    sub.add_parser("clear-sessions", help="Invalidate every auth token; force re-login.")

    pr = sub.add_parser(
        "prune-uploads",
        help="List uploads larger than --min-mb (read-only).",
    )
    pr.add_argument("--min-mb", type=int, default=100)

    ri = sub.add_parser(
        "recover-images",
        help="Export every image asset per user into recovery-images/<name>/ "
             "(or a per-user ZIP). Works from the file_assets table so each "
             "image lands under the account that owns it.",
    )
    ri.add_argument("--user", default="", help="limit to one username (default: all users)")
    ri.add_argument("--zip", action="store_true", help="produce one ZIP per user instead of a folder")
    ri.add_argument("--out", default="", help="output root (default: recovery-images/ in the repo)")

    return p


_COMMANDS = {
    "status": cmd_status,
    "backup": cmd_backup,
    "list-users": cmd_list_users,
    "reset-password": cmd_reset_password,
    "unlock-all": cmd_unlock_all,
    "clear-sessions": cmd_clear_sessions,
    "prune-uploads": cmd_prune_uploads,
    "recover-images": cmd_recover_images,
}


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    fn = _COMMANDS[args.cmd]
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
