"""Edition + OllaBridge Local sidecar surface."""


def test_edition_endpoint(client):
    r = client.get("/v1/edition")
    assert r.status_code == 200
    d = r.json()
    assert d["edition"] in ("web", "local")
    assert d["is_web"] == (d["edition"] == "web")
    assert d["is_local"] == (d["edition"] == "local")
    assert d["can_provide_gpu"] == (d["edition"] == "local")
    assert "cloud_url" in d


def test_local_status_shape(client):
    r = client.get("/v1/ollabridge/local/status")
    assert r.status_code == 200
    d = r.json()
    # Stable contract the frontend depends on.
    for key in ("edition", "available", "installed", "running", "cloud_url", "share_scope"):
        assert key in d
    assert d["share_scope"] == "owner_only"  # never auto-share


def test_pair_url(client):
    r = client.get("/v1/ollabridge/local/pair-url")
    assert r.status_code == 200
    d = r.json()
    assert "pair_url" in d and "cloud_url" in d
    if d["cloud_url"]:
        assert d["pair_url"].endswith("/link")


def test_control_endpoints_are_honest(client):
    # These must never 500; they return an ok/detail contract.
    for path in ("/v1/ollabridge/local/start", "/v1/ollabridge/local/stop"):
        r = client.post(path, json={})
        assert r.status_code == 200
        assert "ok" in r.json()
