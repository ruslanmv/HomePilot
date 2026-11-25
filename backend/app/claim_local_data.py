"""
Give every piece of local data to one local account.

On a single-person HomePilot, data can end up spread over several accounts:
an OllaBridge sign-in creates its own local profile, old installs left rows
with no owner, and test accounts made on the way keep a few items. This tool
moves all of it to the account you name, so it shows up when you sign in as
that account.

    cd backend
    python -m app.claim_local_data ruslanmv            # preview only, changes nothing
    python -m app.claim_local_data ruslanmv --apply    # back up the database, then move

What moves: rows in the tables below whose owner is empty, or is another real
account in the ``users`` table. Owner ids that are not real accounts (test
fixtures such as ``u_smoke_…``) are left alone so they do not flood your lists.

What stays: the other accounts themselves, their sign-in sessions and their
per-account settings (``user_profiles``, ``user_secrets``), which belong to the
account rather than to your content.

Stop HomePilot first if you can; the move runs in one transaction either way.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import time
from typing import Dict, List, Optional, Tuple

from . import users as _users

# (table, owner column). Only tables whose rows are content: chats, media,
# projects, persona sessions, interactive experiences.
OWNED_TABLES: List[Tuple[str, str]] = [
    ("conversation_owners", "user_id"),
    ("messages", "user_id"),
    ("file_assets", "user_id"),
    ("assets", "user_id"),
    ("project_acl", "owner_user_id"),
    ("project_items", "user_id"),
    ("project_activity", "user_id"),
    ("project_members", "user_id"),
    ("persona_sessions", "user_id"),
    ("ix_experiences", "user_id"),
    ("user_memory_items", "user_id"),
]


def _existing(con: sqlite3.Connection) -> List[Tuple[str, str]]:
    out = []
    for table, col in OWNED_TABLES:
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        if col in cols:
            out.append((table, col))
    return out


def _where(target_id: str, others: List[str], col: str) -> Tuple[str, list]:
    marks = ",".join("?" for _ in others) or "NULL"
    return f"({col} IS NULL OR {col} = '' OR {col} IN ({marks}))", list(others)


def plan(con: sqlite3.Connection, target_id: str) -> Dict[str, Dict[str, int]]:
    """Per table, how many rows would move and from whom."""
    names = {r[0]: r[1] for r in con.execute("SELECT id, username FROM users")}
    others = [i for i in names if i != target_id]
    result: Dict[str, Dict[str, int]] = {}
    for table, col in _existing(con):
        where, params = _where(target_id, others, col)
        rows = con.execute(
            f"SELECT {col}, COUNT(*) FROM {table} WHERE {where} GROUP BY 1", params
        ).fetchall()
        if rows:
            result[table] = {(names.get(v) or "(no owner)"): n for v, n in rows}
    return result


def backup(db_path: str) -> str:
    dest = f"{db_path}.bak-{time.strftime('%Y%m%d-%H%M%S')}-before-claim"
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(dest)
    src.backup(dst)
    dst.close()
    src.close()
    return dest


def apply(con: sqlite3.Connection, target_id: str) -> Dict[str, int]:
    names = {r[0] for r in con.execute("SELECT id FROM users")}
    others = [i for i in names if i != target_id]
    moved: Dict[str, int] = {}
    with con:
        for table, col in _existing(con):
            where, params = _where(target_id, others, col)
            n = con.execute(
                f"UPDATE {table} SET {col} = ? WHERE {where}", [target_id, *params]
            ).rowcount
            if n:
                moved[table] = n
    return moved


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.claim_local_data",
        description="Move all local HomePilot data to one local account.",
    )
    parser.add_argument("account", help="username of the local account that should own everything")
    parser.add_argument("--apply", action="store_true", help="make the change (default: preview only)")
    args = parser.parse_args(argv)

    _users.ensure_users_tables()
    user = _users.get_user_by_username(args.account)
    if not user or (user.get("auth_provider") or "local") != "local":
        print(f"No local account named '{args.account}'.")
        return 1

    db_path = _users._get_db_path()
    con = sqlite3.connect(db_path, timeout=30)
    todo = plan(con, user["id"])
    if not todo:
        print(f"Everything already belongs to '{user['username']}'. Nothing to do.")
        return 0

    total = 0
    print(f"Rows to move to '{user['username']}':")
    for table, by_owner in todo.items():
        n = sum(by_owner.values())
        total += n
        detail = ", ".join(f"{k}: {v}" for k, v in sorted(by_owner.items()))
        print(f"  {table:<22} {n:>6}   ({detail})")
    print(f"  {'total':<22} {total:>6}")

    if not args.apply:
        print("\nPreview only. Run again with --apply to move them.")
        return 0

    con.close()
    saved = backup(db_path)
    print(f"\nBacked up the database to {saved}")
    con = sqlite3.connect(db_path, timeout=30)
    moved = apply(con, user["id"])
    left = plan(con, user["id"])
    con.close()
    print(f"Moved {sum(moved.values())} rows. Left to move: {sum(sum(v.values()) for v in left.values())}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
