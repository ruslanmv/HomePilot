"""Project Chat → Tasks: a checklist stored on the project; the assistant sees the open ones."""
from __future__ import annotations

import sys


def test_tasks_are_cleaned_and_open_ones_reach_the_prompt():
    projects = sys.modules.get("app.projects") or __import__("app.projects", fromlist=["x"])
    rows = projects.clean_tasks([
        {"text": "  Rig the face ", "done": False},
        {"text": "", "done": False},
        "junk",
        {"id": "t2", "text": "Export GLB", "done": True},
    ])
    assert [r["text"] for r in rows] == ["Rig the face", "Export GLB"]
    assert rows[1]["id"] == "t2" and all(r["id"] for r in rows)
    hint = projects.open_tasks_hint({"tasks": rows})
    assert "Rig the face" in hint and "Export GLB" not in hint
    assert projects.open_tasks_hint({}) == ""


def test_tasks_save_through_the_project_api(client):
    created = client.post("/projects", json={"name": "Tasks demo", "project_type": "chat"}).json()
    pid = (created.get("project") or created)["id"]
    r = client.put(f"/projects/{pid}", json={"tasks": [{"text": "Write README", "done": False}]})
    assert r.status_code == 200, r.text
    got = client.get(f"/projects/{pid}").json()["project"]
    assert [t["text"] for t in got["tasks"]] == ["Write README"]
