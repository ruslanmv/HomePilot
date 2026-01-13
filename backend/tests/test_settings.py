def test_settings_ok(client, mock_outbound):
    r = client.get("/settings")
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert "default_provider" in data
    assert "llm_base_url" in data
    assert "comfy_base_url" in data
