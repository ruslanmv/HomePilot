"""A meeting's first write into its brand-new conversation.

MeetingSense opens every meeting in a fresh conversation with a client-chosen id
and posts a "Meeting started" marker through ``POST /conversations/{id}/messages``
before any chat turn exists. For a signed-in user that used to be a 404 ("the
conversation has no messages, so it is not yours"), and the marker was lost.
Now an unowned conversation is claimed by the first writer; one owned by
someone else is still a 404, so the endpoint stays probe-safe.
"""
import uuid


def _register(client, username, password="pw"):
    return client.post("/v1/auth/register", json={
        "username": username,
        "password": password,
        "email": "",
        "display_name": username,
    })


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _marker(client, token, cid):
    return client.post(
        f"/conversations/{cid}/messages",
        headers=_auth(token),
        json={"role": "system", "content": "Meeting started"},
    )


def test_first_marker_into_a_new_conversation_claims_it(client):
    token = _register(client, f"marker_owner_{uuid.uuid4().hex[:8]}").json()["token"]
    cid = f"meeting-{uuid.uuid4()}"

    res = _marker(client, token, cid)
    assert res.status_code in (200, 201), res.text

    msgs = client.get(f"/conversations/{cid}/messages", headers=_auth(token)).json()
    assert [m["content"] for m in msgs.get("messages", [])] == ["Meeting started"]


def test_a_conversation_owned_by_someone_else_is_still_not_found(client):
    owner = _register(client, f"marker_a_{uuid.uuid4().hex[:8]}").json()["token"]
    other = _register(client, f"marker_b_{uuid.uuid4().hex[:8]}").json()["token"]
    cid = f"meeting-{uuid.uuid4()}"

    assert _marker(client, owner, cid).status_code in (200, 201)
    assert _marker(client, other, cid).status_code == 404

    spy = client.get(f"/conversations/{cid}/messages", headers=_auth(other)).json()
    assert spy.get("messages", []) == []
    mine = client.get(f"/conversations/{cid}/messages", headers=_auth(owner)).json()
    assert len(mine.get("messages", [])) == 1
