def test_chat_with_ollama_provider(client, mock_outbound):
    payload = {
        "message": "hello from ollama",
        "conversation_id": "test-ollama",
        "fun_mode": False,
        "mode": "chat",
        "provider": "ollama",
    }
    r = client.post("/chat", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["conversation_id"] == "test-ollama"
    assert "text" in data
    assert isinstance(data["text"], str)
