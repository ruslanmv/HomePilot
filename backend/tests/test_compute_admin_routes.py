"""PR 2 — compute admin API (/compute/admin/*).

Exercises the CRUD + resolve endpoints through the real FastAPI app. The test
cleans up everything it creates so it doesn't perturb the shared session DB that
other tests route against.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_compute_admin_crud_and_resolve(client):
    # Create an OpenAI-compatible source with an inline credential (write-only).
    r = client.post("/compute/admin/sources", json={
        "id": "oa-test", "name": "OpenAI compat", "kind": "openai_compatible",
        "base_url": "http://endpoint", "credential": "sk-secret",
    })
    assert r.status_code == 200, r.text
    src = r.json()["source"]
    assert src["credential_ref"]                 # a ref was minted
    assert "credential" not in src               # secret never echoed back

    # It appears in the list.
    listed = client.get("/compute/admin/sources").json()["sources"]
    assert any(s["id"] == "oa-test" for s in listed)

    # Pin a model to that source with a local fallback.
    r = client.post("/compute/admin/routes", json={
        "modality": "chat", "model_id": "svc-model", "primary_target": "source:oa-test",
        "fallback_targets": ["local"], "strategy": "pinned",
    })
    assert r.status_code == 200, r.text

    # Resolve explains the plan.
    plan = client.get("/compute/admin/resolve", params={
        "modality": "chat", "model_id": "svc-model"}).json()
    assert plan["matched"] == "route"
    assert plan["targets"][0] == "source:oa-test"
    assert "local" in plan["targets"]            # safe tail

    # Missing required fields are rejected.
    assert client.post("/compute/admin/routes", json={"modality": "chat"}).status_code == 400

    # Cleanup so the shared DB is left as we found it.
    assert client.delete("/compute/admin/routes/chat/svc-model").status_code == 200
    assert client.delete("/compute/admin/sources/oa-test").status_code == 200
    assert not any(
        s["id"] == "oa-test" for s in client.get("/compute/admin/sources").json()["sources"]
    )
