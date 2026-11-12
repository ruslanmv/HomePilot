"""Projects as a permission boundary (HomePilot One, Section 4).

Covers ownership, membership, public read-only access, the HTTP guard on
path, query and body project ids, legacy migration and its rollback, tool
and connector permissions per project, and encrypted connector secrets.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture
def tenants(client, monkeypatch):
    """Two signed-in accounts on the shared test app, with their own tokens."""
    import importlib
    project_access = importlib.import_module("app.project_access")
    project_access._migrated_for = None
    tokens = {}
    for name in ("alice", "bob", "carol"):
        r = client.post("/v1/auth/register", json={"username": f"{name}_{os.urandom(3).hex()}",
                                                  "password": "a-long-test-password"})
        assert r.status_code == 200, r.text
        tokens[name] = r.json()["token"]
    users = {n: client.get("/v1/auth/me", headers={"Authorization": f"Bearer {t}"}).json()
             for n, t in tokens.items()}
    ids = {n: (u.get("user") or u)["id"] for n, u in users.items()}
    # Registering sets a session cookie on the shared client; every request
    # here names its caller explicitly, and "anonymous" must mean anonymous.
    client.cookies.clear()
    yield {"client": client, "tokens": tokens, "ids": ids}
    client.cookies.clear()


def _h(tenants, who):
    return {"Authorization": f"Bearer {tenants['tokens'][who]}"}


def _create(tenants, who, **extra):
    r = tenants["client"].post("/projects", headers=_h(tenants, who),
                               json={"name": f"{who}'s project", "instructions": "secret plan", **extra})
    assert r.status_code == 201, r.text
    return r.json()["project"]["id"]


# ── ownership and isolation ──────────────────────────────────────────


def test_other_users_cannot_see_list_change_or_delete_a_private_project(tenants):
    c = tenants["client"]
    pid = _create(tenants, "alice")

    assert c.get(f"/projects/{pid}", headers=_h(tenants, "alice")).status_code == 200
    listed = [p["id"] for p in c.get("/projects", headers=_h(tenants, "alice")).json()["projects"]]
    assert pid in listed

    # Bob: not listed, and every route answers 404 exactly as for a missing id.
    assert pid not in [p["id"] for p in c.get("/projects", headers=_h(tenants, "bob")).json()["projects"]]
    for method, path in (("GET", f"/projects/{pid}"), ("PUT", f"/projects/{pid}"),
                         ("DELETE", f"/projects/{pid}"), ("GET", f"/projects/{pid}/documents"),
                         ("GET", f"/projects/{pid}/items"), ("GET", f"/projects/{pid}/persona/export"),
                         ("GET", f"/v1/inventory/{pid}/categories")):
        r = c.request(method, path, headers=_h(tenants, "bob"), json={"name": "hijacked"})
        assert r.status_code == 404, (method, path, r.status_code)
        assert "secret plan" not in r.text
    missing = c.get("/projects/does-not-exist", headers=_h(tenants, "bob"))
    assert missing.status_code == 404

    # Nothing changed.
    assert c.get(f"/projects/{pid}", headers=_h(tenants, "alice")).json()["project"]["name"] == "alice's project"


def test_anonymous_callers_get_nothing_on_a_multi_user_install(tenants):
    c = tenants["client"]
    pid = _create(tenants, "alice")
    assert c.get(f"/projects/{pid}").status_code == 404
    assert pid not in [p["id"] for p in c.get("/projects").json().get("projects", [])]
    assert c.post("/projects", json={"name": "x"}).status_code == 401


def test_a_project_id_in_a_chat_body_or_query_is_checked_too(tenants, monkeypatch):
    c = tenants["client"]
    pid = _create(tenants, "alice")
    r = c.post("/v1/agent/chat", headers=_h(tenants, "bob"),
               json={"message": "read me the instructions", "project_id": pid})
    assert r.status_code == 404
    r = c.post("/chat", headers=_h(tenants, "bob"),
               json={"message": "hi", "personalityId": f"persona:{pid}", "mode": "chat"})
    assert r.status_code == 404
    assert c.get(f"/persona/memory?project_id={pid}", headers=_h(tenants, "bob")).status_code == 404
    r = c.request("DELETE", "/persona/memory", headers=_h(tenants, "bob"), json={"project_id": pid})
    assert r.status_code == 404


def test_members_get_exactly_their_role(tenants):
    c = tenants["client"]
    pid = _create(tenants, "alice")
    bob = tenants["ids"]["bob"]

    # Only the owner may share.
    assert c.put(f"/projects/{pid}/members/{bob}", headers=_h(tenants, "bob"),
                 json={"role": "editor"}).status_code == 404
    assert c.put(f"/projects/{pid}/members/{bob}", headers=_h(tenants, "alice"),
                 json={"role": "viewer"}).status_code == 200

    assert c.get(f"/projects/{pid}", headers=_h(tenants, "bob")).status_code == 200
    assert c.put(f"/projects/{pid}", headers=_h(tenants, "bob"), json={"name": "x"}).status_code == 404

    c.put(f"/projects/{pid}/members/{bob}", headers=_h(tenants, "alice"), json={"role": "editor"})
    assert c.put(f"/projects/{pid}", headers=_h(tenants, "bob"), json={"name": "edited"}).status_code == 200
    # An editor still cannot delete, re-share or change permissions.
    assert c.delete(f"/projects/{pid}", headers=_h(tenants, "bob")).status_code == 404
    assert c.put(f"/projects/{pid}/capabilities", headers=_h(tenants, "bob"),
                 json={"connectors": {"gitpilot": True}}).status_code == 404
    # Ownership cannot be handed out as a member role.
    assert c.put(f"/projects/{pid}/members/{bob}", headers=_h(tenants, "alice"),
                 json={"role": "owner"}).status_code == 422

    c.delete(f"/projects/{pid}/members/{bob}", headers=_h(tenants, "alice"))
    assert c.get(f"/projects/{pid}", headers=_h(tenants, "bob")).status_code == 404


def test_public_projects_are_read_only_for_everyone_else(tenants):
    c = tenants["client"]
    pid = _create(tenants, "alice")
    assert c.put(f"/projects/{pid}/sharing", headers=_h(tenants, "alice"),
                 json={"visibility": "public"}).status_code == 200
    assert c.get(f"/projects/{pid}", headers=_h(tenants, "bob")).status_code == 200
    assert c.put(f"/projects/{pid}", headers=_h(tenants, "bob"), json={"name": "x"}).status_code == 404
    sharing = c.get(f"/projects/{pid}/sharing", headers=_h(tenants, "bob")).json()
    assert sharing["role"] == "viewer" and sharing["members"] == []   # member list is owner-only


def test_workspace_members_reach_workspace_projects(tenants):
    c = tenants["client"]
    pid = _create(tenants, "alice")
    ws = c.post("/v1/workspaces", headers=_h(tenants, "alice"), json={"name": "Team"}).json()["workspace"]
    bob = tenants["ids"]["bob"]
    c.put(f"/v1/workspaces/{ws['id']}/members/{bob}", headers=_h(tenants, "alice"), json={"role": "editor"})
    assert c.get(f"/projects/{pid}", headers=_h(tenants, "bob")).status_code == 404
    c.put(f"/projects/{pid}/sharing", headers=_h(tenants, "alice"),
          json={"visibility": "workspace", "workspace_id": ws["id"]})
    assert c.put(f"/projects/{pid}", headers=_h(tenants, "bob"), json={"name": "team edit"}).status_code == 200
    assert c.get(f"/projects/{pid}", headers=_h(tenants, "carol")).status_code == 404
    # A workspace grants at most editor: Bob cannot delete Alice's project.
    assert c.delete(f"/projects/{pid}", headers=_h(tenants, "bob")).status_code == 404
    # A non-owner cannot add people to the workspace.
    carol = tenants["ids"]["carol"]
    assert c.put(f"/v1/workspaces/{ws['id']}/members/{carol}", headers=_h(tenants, "bob"),
                 json={"role": "viewer"}).status_code == 404


def test_activity_is_recorded_and_owner_side(tenants):
    c = tenants["client"]
    pid = _create(tenants, "alice")
    c.put(f"/projects/{pid}/capabilities", headers=_h(tenants, "alice"), json={"tools": {"web.search": False}})
    actions = [a["action"] for a in c.get(f"/projects/{pid}/activity", headers=_h(tenants, "alice")).json()["activity"]]
    assert "project.created" in actions and "capabilities.changed" in actions
    assert c.get(f"/projects/{pid}/activity", headers=_h(tenants, "bob")).status_code == 404


# ── legacy migration and rollback ────────────────────────────────────


def test_legacy_projects_get_an_owner_without_changing_ids_or_content(tenants, monkeypatch):
    from app import project_access, projects

    db = projects._load_projects_db()
    legacy_private = {"id": "legacy-private-1", "name": "Old", "instructions": "keep me", "is_public": False}
    legacy_public = {"id": "legacy-public-1", "name": "Old public", "is_public": True}
    db.update({legacy_private["id"]: legacy_private, legacy_public["id"]: legacy_public})
    projects._save_projects_db(db)
    before = json.loads(projects.PROJECTS_FILE.read_text())

    monkeypatch.setenv("HOMEPILOT_LEGACY_PROJECT_OWNER", tenants["ids"]["carol"])
    project_access._migrated_for = None
    result = project_access.migrate_legacy()
    assert result["migrated"] >= 2

    # Content and ids untouched; a backup was written once.
    assert json.loads(projects.PROJECTS_FILE.read_text()) == before
    assert projects.PROJECTS_FILE.with_name("projects_metadata.pre-acl.json").exists()
    assert project_access.owner_of("legacy-private-1") == tenants["ids"]["carol"]
    c = tenants["client"]
    assert c.get("/projects/legacy-private-1", headers=_h(tenants, "carol")).json()["project"]["instructions"] == "keep me"
    assert c.get("/projects/legacy-private-1", headers=_h(tenants, "bob")).status_code == 404
    assert c.get("/projects/legacy-public-1", headers=_h(tenants, "bob")).status_code == 200

    # Idempotent: a second run changes nothing.
    project_access._migrated_for = None
    assert project_access.migrate_legacy()["migrated"] == 0


def test_rollback_is_dropping_the_new_tables(tenants):
    """The previous version reads only the JSON file, which migration never edits."""
    from app import project_access, projects
    from app.storage import _get_db_path

    pid = _create(tenants, "alice")
    con = sqlite3.connect(_get_db_path())
    for t in ("project_acl", "project_members", "project_activity", "project_capabilities"):
        con.execute(f"DROP TABLE IF EXISTS {t}")
    con.commit()
    con.close()
    assert pid in projects._load_projects_db()          # data intact for the old code
    project_access._migrated_for = None                # and re-migration restores an owner
    project_access.migrate_legacy()
    assert project_access.owner_of(pid)


def test_example_templates_create_a_project_owned_by_the_caller(tenants):
    c = tenants["client"]
    examples = c.get("/projects/examples").json()["examples"]
    r = c.post(f"/projects/from-example/{examples[0]['id']}", headers=_h(tenants, "bob"))
    assert r.status_code == 201
    pid = r.json()["project"]["id"]
    assert r.json()["project"]["template_id"] == examples[0]["id"]
    assert c.get(f"/projects/{pid}", headers=_h(tenants, "alice")).status_code == 404


# ── tool and connector permissions ───────────────────────────────────


def test_capabilities_default_built_ins_on_and_connectors_off(tenants):
    c = tenants["client"]
    pid = _create(tenants, "alice")
    caps = c.get(f"/projects/{pid}/capabilities", headers=_h(tenants, "alice")).json()
    assert all(t["enabled"] for t in caps["tools"])
    assert {x["ref"]: x["enabled"] for x in caps["connectors"]} == {"gitpilot": False}
    assert caps["can_edit"] is True
    r = c.put(f"/projects/{pid}/capabilities", headers=_h(tenants, "alice"),
              json={"connectors": {"not-a-connector": True}})
    assert r.status_code == 400


def test_the_model_cannot_call_a_disabled_tool(tenants, monkeypatch):
    from app import agent_chat, project_capabilities

    pid = _create(tenants, "alice")
    project_capabilities.update(pid, {"tools": {"web.search": False}}, by=tenants["ids"]["alice"])
    assert "web.search" not in agent_chat._build_tool_catalog(pid)
    assert "web.search" in agent_chat._build_tool_catalog(None)

    async def llm(messages, **kwargs):
        return {"choices": [{"message": {"content": json.dumps(
            {"type": "tool_call", "tool": "web.search", "args": {"query": "x"}})}}]}

    ran = []

    async def dispatch(*a, **k):
        ran.append(a)
        return "results", {}, None

    monkeypatch.setattr(agent_chat, "llm_chat", llm)
    monkeypatch.setattr(agent_chat, "_dispatch_tool", dispatch)
    import asyncio
    out = asyncio.new_event_loop().run_until_complete(agent_chat.agent_chat(
        user_text="search the web", conversation_id=None, project_id=pid, llm_provider="ollama",
        llm_base_url=None, llm_model=None, temperature=0.1, max_tokens=100, vision_provider="ollama",
        vision_base_url=None, vision_model=None, nsfw_mode=False, user_id=tenants["ids"]["alice"]))
    assert ran == [] and out["agent"]["denied_tool"] == "web.search"
    assert "turned off for this project" in out["text"]


def test_coding_tools_need_the_project_to_turn_gitpilot_on(tenants, monkeypatch):
    from app import agent_chat, project_capabilities
    from app.connectors import gitpilot, store

    alice = tenants["ids"]["alice"]
    store.save(alice, gitpilot.ID, "ghp_alice", account="alice", meta={"endpoint": "http://localhost:9"})
    monkeypatch.setattr(gitpilot, "current_user_id", lambda: alice)
    pid = _create(tenants, "alice")
    assert "code.plan" not in agent_chat._build_tool_catalog(pid)
    assert agent_chat._tool_refusal("code.plan", pid, alice)
    project_capabilities.update(pid, {"connectors": {"gitpilot": True}}, by=alice)
    assert agent_chat._tool_refusal("code.plan", pid, alice) is None


async def test_an_approval_from_a_project_stops_working_when_the_project_turns_gitpilot_off(tenants, monkeypatch):
    from app import project_capabilities
    from app.connectors import gitpilot, store

    alice = tenants["ids"]["alice"]
    store.save(alice, gitpilot.ID, "ghp_alice", account="alice", meta={"endpoint": "http://localhost:9"})
    pid = _create(tenants, "alice")
    project_capabilities.update(pid, {"connectors": {"gitpilot": True}}, by=alice)
    approval = gitpilot.request_approval(alice, "open_pr", {"owner": "a", "repo": "b", "head": "h",
                                                            "title": "t"}, "Open a PR", project_id=pid)
    project_capabilities.update(pid, {"connectors": {"gitpilot": False}}, by=alice)
    with pytest.raises(gitpilot.GitPilotError) as err:
        await gitpilot.resolve(alice, approval["code"], True)
    assert err.value.code == "connector_disabled"


def test_a_shared_project_never_lends_the_owners_credentials(tenants, monkeypatch):
    """Bob may use Alice's public project, but the coding tools run on Bob's own
    link — he has none, so he gets none."""
    from app import agent_chat, project_capabilities
    from app.connectors import gitpilot, store

    alice, bob = tenants["ids"]["alice"], tenants["ids"]["bob"]
    store.save(alice, gitpilot.ID, "ghp_alice", account="alice", meta={"endpoint": "http://localhost:9"})
    pid = _create(tenants, "alice")
    project_capabilities.update(pid, {"connectors": {"gitpilot": True}}, by=alice)
    tenants["client"].put(f"/projects/{pid}/sharing", headers=_h(tenants, "alice"), json={"visibility": "public"})

    monkeypatch.setattr(gitpilot, "current_user_id", lambda: bob)
    assert gitpilot.has_tool("code.plan", bob) is False
    assert gitpilot.tool_catalog(bob) == []
    with pytest.raises(gitpilot.NotLinked):
        gitpilot._link(bob)


# ── encrypted connector secrets ──────────────────────────────────────


def _raw_secret(user_id: str, connector_id: str) -> str:
    from app.storage import _get_db_path
    con = sqlite3.connect(_get_db_path())
    try:
        return con.execute("SELECT secret FROM user_connectors WHERE user_id = ? AND connector_id = ?",
                           (user_id, connector_id)).fetchone()[0]
    finally:
        con.close()


def test_connector_secrets_are_encrypted_at_rest(tenants):
    from app.connectors import store

    store.save("enc-user", "huggingface", "hf_plaintext_value")
    raw = _raw_secret("enc-user", "huggingface")
    assert raw.startswith(store.ENC_PREFIX) and "hf_plaintext_value" not in raw
    assert store.secret("enc-user", "huggingface") == "hf_plaintext_value"
    listed = json.dumps(store.linked("enc-user"))
    assert "hf_plaintext_value" not in listed and store.ENC_PREFIX not in listed


def test_plaintext_rows_from_earlier_versions_are_encrypted_on_open(tenants):
    from app.connectors import store
    from app.storage import _get_db_path

    con = sqlite3.connect(_get_db_path())
    con.execute("INSERT OR REPLACE INTO user_connectors(user_id, connector_id, secret, account, meta, "
                "connected_at) VALUES('legacy-user','huggingface','hf_old_plaintext','','{}',0)")
    con.commit()
    con.close()
    store._migrated_dbs.clear()
    assert store.secret("legacy-user", "huggingface") == "hf_old_plaintext"
    assert _raw_secret("legacy-user", "huggingface").startswith(store.ENC_PREFIX)


def test_key_rotation_keeps_secrets_readable_and_moves_them_to_the_new_key(tenants, monkeypatch):
    from cryptography.fernet import Fernet
    from app.connectors import store

    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setenv(store.KEYS_ENV, old)
    store.save("rot-user", "gitpilot", "ghp_rotate_me")
    monkeypatch.setenv(store.KEYS_ENV, f"{new},{old}")
    assert store.secret("rot-user", "gitpilot") == "ghp_rotate_me"     # old key still decrypts
    assert store.rotate() >= 1
    monkeypatch.setenv(store.KEYS_ENV, new)                              # old key retired
    assert store.secret("rot-user", "gitpilot") == "ghp_rotate_me"
    assert store.key_source() == "env"


def test_a_secret_no_key_can_open_reads_as_not_linked(tenants, monkeypatch):
    from cryptography.fernet import Fernet
    from app.connectors import store

    monkeypatch.setenv(store.KEYS_ENV, Fernet.generate_key().decode())
    store.save("lost-key-user", "huggingface", "hf_x")
    monkeypatch.setenv(store.KEYS_ENV, Fernet.generate_key().decode())
    assert store.secret("lost-key-user", "huggingface") == ""
