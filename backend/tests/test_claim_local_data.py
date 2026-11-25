"""claim_local_data: move content from other real accounts and from no owner to one account."""
import importlib
import sqlite3
import sys
import uuid


def _mod(name):
    return sys.modules.get(name) or importlib.import_module(name)


def test_moves_real_and_ownerless_rows_but_not_test_ids(app, client):
    users = _mod("app.users")
    claim = _mod("app.claim_local_data")
    tag = uuid.uuid4().hex[:8]
    me = users.create_user(username=f"me{tag}", password="pw123456")
    other = users.create_user(username=f"other{tag}", password="pw123456")

    con = sqlite3.connect(users._get_db_path())
    con.execute("CREATE TABLE IF NOT EXISTS conversation_owners(conversation_id TEXT PRIMARY KEY, user_id TEXT)")
    con.executemany(
        "INSERT INTO conversation_owners(conversation_id, user_id) VALUES (?, ?)",
        [(f"c1{tag}", other["id"]), (f"c2{tag}", ""), (f"c3{tag}", f"u_smoke_{tag}"), (f"c4{tag}", me["id"])],
    )
    con.commit()

    preview = claim.plan(con, me["id"])["conversation_owners"]
    assert preview.get(other["username"]) == 1
    assert preview.get("(no owner)", 0) >= 1

    claim.apply(con, me["id"])
    owners = dict(con.execute(
        "SELECT conversation_id, user_id FROM conversation_owners WHERE conversation_id LIKE ?", (f"%{tag}",)
    ).fetchall())
    con.close()
    assert owners[f"c1{tag}"] == me["id"]
    assert owners[f"c2{tag}"] == me["id"]
    assert owners[f"c3{tag}"] == f"u_smoke_{tag}"  # not a real account: left alone
    assert owners[f"c4{tag}"] == me["id"]


def test_main_preview_changes_nothing(app, client, capsys):
    users = _mod("app.users")
    claim = _mod("app.claim_local_data")
    tag = uuid.uuid4().hex[:8]
    me = users.create_user(username=f"pv{tag}", password="pw123456")
    con = sqlite3.connect(users._get_db_path())
    before = con.execute("SELECT COUNT(*) FROM conversation_owners WHERE user_id = ?", (me["id"],)).fetchone()[0]
    con.close()
    assert claim.main([me["username"]]) == 0
    con = sqlite3.connect(users._get_db_path())
    after = con.execute("SELECT COUNT(*) FROM conversation_owners WHERE user_id = ?", (me["id"],)).fetchone()[0]
    con.close()
    assert before == after
