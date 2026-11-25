"""roles_for (one lookup for many projects) gives the same answers as role_for."""
import importlib
import sqlite3
import sys
import time
import uuid


def _mod(name):
    return sys.modules.get(name) or importlib.import_module(name)


def test_roles_for_matches_role_for(app, client):
    users = _mod("app.users")
    pa = _mod("app.project_access")
    projects = _mod("app.projects")
    pa.migrate_legacy()
    tag = uuid.uuid4().hex[:8]
    owner = users.create_user(username=f"ow{tag}", password="pw123456")["id"]
    member = users.create_user(username=f"me{tag}", password="pw123456")["id"]
    stranger = users.create_user(username=f"st{tag}", password="pw123456")["id"]

    con = sqlite3.connect(users._get_db_path())
    now = time.time()
    ids = {k: f"p_{k}_{tag}" for k in ("private", "public", "shared", "workspace")}
    ws = f"ws_{tag}"
    con.execute("INSERT INTO workspaces(id, name, created_by, created_at) VALUES (?,?,?,?)", (ws, "W", owner, now))
    con.execute("INSERT INTO workspace_members(workspace_id, user_id, role) VALUES (?,?,?)", (ws, stranger, "owner"))
    for kind, pid in ids.items():
        vis = {"public": "public", "workspace": "workspace"}.get(kind, "private")
        con.execute(
            "INSERT INTO project_acl(project_id, owner_user_id, workspace_id, visibility, created_at, migrated) "
            "VALUES (?,?,?,?,?,0)",
            (pid, owner, ws if kind == "workspace" else None, vis, now),
        )
    con.execute("INSERT INTO project_members(project_id, user_id, role, added_by, added_at) VALUES (?,?,?,?,?)",
                (ids["shared"], member, "editor", owner, now))
    con.commit()
    con.close()

    all_ids = list(ids.values()) + list(projects.EXAMPLE_PROJECTS)[:2] + ["missing_project"]
    for uid in (owner, member, stranger, ""):
        bulk = pa.roles_for(all_ids, uid)
        for pid in all_ids:
            assert bulk[pid] == pa.role_for(pid, uid), (uid, pid)

    # Spot checks of the rules themselves.
    assert pa.roles_for([ids["private"]], stranger)[ids["private"]] is None
    assert pa.roles_for([ids["shared"]], member)[ids["shared"]] == "editor"
    assert pa.roles_for([ids["workspace"]], stranger)[ids["workspace"]] == "editor"  # workspace caps at editor
    assert pa.roles_for([ids["public"]], "")[ids["public"]] == "viewer"
