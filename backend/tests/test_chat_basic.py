def test_chat_basic_returns_text_and_media_key(client, mock_outbound):
    payload = {
        "message": "hello",
        "conversation_id": "test-conv",
        "fun_mode": False,
        "mode": "chat",
    }
    r = client.post("/chat", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()

    assert "conversation_id" in data
    assert "text" in data
    assert isinstance(data["text"], str)
    assert "media" in data
