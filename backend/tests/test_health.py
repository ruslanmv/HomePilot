def test_health_ok(client, mock_outbound):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict)
    assert data.get("ok") is True
    assert data.get("service") == "homepilot-backend"
