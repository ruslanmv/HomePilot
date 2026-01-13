def test_providers_ok(client, mock_outbound):
    r = client.get("/providers")
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert "default" in data
    assert "available" in data
    assert isinstance(data["available"], list)
