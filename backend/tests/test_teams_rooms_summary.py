"""The Teams landing list leaves transcripts out; ?full=1 and single rooms keep them."""
import importlib
import json
import sys
import time
import uuid


def test_room_list_is_summary_by_default(app, client, tmp_path, monkeypatch):
    rooms = sys.modules.get("app.teams.rooms") or importlib.import_module("app.teams.rooms")
    monkeypatch.setattr(rooms, "_ensure_dir", lambda: tmp_path)
    rid = str(uuid.uuid4())
    msgs = [{"id": f"m{i}", "role": "assistant", "content": "x" * 500, "timestamp": time.time() + i} for i in range(5)]
    (tmp_path / f"{rid}.json").write_text(json.dumps({
        "id": rid, "name": "R", "participant_ids": ["a", "b"], "messages": msgs, "updated_at": 1,
    }), encoding="utf-8")

    listed = client.get("/v1/teams/rooms").json()
    room = next(r for r in listed if r["id"] == rid)
    assert room["messages"] == [] and room["messages_omitted"] is True
    assert room["message_count"] == 5 and room["participant_count"] == 2

    full = next(r for r in client.get("/v1/teams/rooms?full=1").json() if r["id"] == rid)
    assert len(full["messages"]) == 5
    # Internal callers (e.g. the Meetings library) still get transcripts.
    assert len(next(r for r in rooms.list_rooms() if r["id"] == rid)["messages"]) == 5
