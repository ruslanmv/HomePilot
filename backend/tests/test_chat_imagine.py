def test_chat_imagine_returns_media_or_text(client, mock_outbound):
    payload = {
        "message": "imagine a cinematic robot on mars",
        "conversation_id": "test-conv",
        "fun_mode": True,
        "mode": "imagine",
    }
    r = client.post("/chat", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()

    assert "text" in data
    assert isinstance(data["text"], str)

    if data.get("media"):
        assert isinstance(data["media"], dict)
        if "images" in data["media"]:
            assert isinstance(data["media"]["images"], list)
