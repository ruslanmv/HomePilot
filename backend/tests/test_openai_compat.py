"""
Unit tests for the OpenAI-compatible persona API (/v1/chat/completions, /v1/models).

These tests run without external services (Ollama, OllaBridge) by using the
mock_outbound fixture from conftest.py.  They validate:

  1. /v1/models returns built-in personalities in OpenAI format
  2. /v1/chat/completions routes to the correct persona and returns valid output
  3. Model naming convention (persona:*, personality:*, shorthand)
  4. Auth works with both X-API-Key and Authorization: Bearer headers
  5. The runtime toggle (/settings/ollabridge) gates the endpoint
"""
import pytest


# ---------------------------------------------------------------------------
# /v1/models
# ---------------------------------------------------------------------------

class TestOpenAIModels:
    """GET /v1/models — list personas as OpenAI-format models."""

    def test_models_returns_list(self, client, mock_outbound):
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert isinstance(data["data"], list)

    def test_models_include_builtin_personalities(self, client, mock_outbound):
        resp = client.get("/v1/models")
        ids = [m["id"] for m in resp.json()["data"]]
        # At minimum the 'assistant' personality must exist
        assert "personality:assistant" in ids

    def test_models_owned_by_homepilot(self, client, mock_outbound):
        resp = client.get("/v1/models")
        for m in resp.json()["data"]:
            assert m["object"] == "model"
            assert m["owned_by"].startswith("homepilot")

    def test_models_have_required_fields(self, client, mock_outbound):
        resp = client.get("/v1/models")
        for m in resp.json()["data"]:
            assert "id" in m
            assert "object" in m
            assert "created" in m
            assert "owned_by" in m


# ---------------------------------------------------------------------------
# /v1/chat/completions
# ---------------------------------------------------------------------------

class TestOpenAIChatCompletions:
    """POST /v1/chat/completions — persona chat in OpenAI format."""

    def _chat(self, client, model="personality:assistant", content="Hi"):
        return client.post("/v1/chat/completions", json={
            "model": model,
            "messages": [{"role": "user", "content": content}],
        })

    def test_chat_returns_200(self, client, mock_outbound):
        resp = self._chat(client)
        assert resp.status_code == 200

    def test_chat_response_schema(self, client, mock_outbound):
        resp = self._chat(client)
        data = resp.json()
        assert data["object"] == "chat.completion"
        assert data["model"] == "personality:assistant"
        assert len(data["choices"]) == 1
        choice = data["choices"][0]
        assert choice["message"]["role"] == "assistant"
        assert isinstance(choice["message"]["content"], str)
        assert choice["finish_reason"] == "stop"

    def test_chat_has_id_and_created(self, client, mock_outbound):
        data = self._chat(client).json()
        assert data["id"].startswith("homepilot-")
        assert isinstance(data["created"], int)

    def test_chat_personality_shorthand(self, client, mock_outbound):
        """Model='assistant' (no prefix) should resolve to built-in personality."""
        resp = self._chat(client, model="assistant")
        assert resp.status_code == 200

    def test_chat_default_model(self, client, mock_outbound):
        """Model='default' should do a plain LLM passthrough."""
        resp = self._chat(client, model="default")
        assert resp.status_code == 200

    def test_chat_unknown_persona_404(self, client, mock_outbound):
        resp = self._chat(client, model="persona:nonexistent-id-12345")
        assert resp.status_code == 404

    def test_chat_streaming_not_supported(self, client, mock_outbound):
        resp = client.post("/v1/chat/completions", json={
            "model": "personality:assistant",
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": True,
        })
        assert resp.status_code == 501

    def test_chat_system_message_merged(self, client, mock_outbound):
        """System messages from the request should be merged into persona prompt."""
        resp = client.post("/v1/chat/completions", json={
            "model": "personality:assistant",
            "messages": [
                {"role": "system", "content": "Extra context."},
                {"role": "user", "content": "Hi"},
            ],
        })
        assert resp.status_code == 200

    def test_chat_respects_temperature(self, client, mock_outbound):
        resp = client.post("/v1/chat/completions", json={
            "model": "default",
            "messages": [{"role": "user", "content": "Hi"}],
            "temperature": 0.1,
            "max_tokens": 10,
        })
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class TestOpenAIAuth:
    """Auth on the compat endpoints — X-API-Key and Bearer token."""

    def test_no_key_required_when_unset(self, client, mock_outbound):
        """When API_KEY is empty, endpoints should be accessible."""
        resp = client.get("/v1/models")
        assert resp.status_code == 200

    def test_x_api_key_header(self, client, mock_outbound, monkeypatch):
        import app.config as cfg
        monkeypatch.setattr(cfg, "API_KEY", "test-key-123")
        # Wrong key
        resp = client.get("/v1/models", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 401
        # Correct key
        resp = client.get("/v1/models", headers={"X-API-Key": "test-key-123"})
        assert resp.status_code == 200

    def test_bearer_token_header(self, client, mock_outbound, monkeypatch):
        import app.config as cfg
        monkeypatch.setattr(cfg, "API_KEY", "test-key-456")
        # Wrong token
        resp = client.get("/v1/models", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401
        # Correct token
        resp = client.get("/v1/models", headers={"Authorization": "Bearer test-key-456"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Runtime toggle (/settings/ollabridge)
# ---------------------------------------------------------------------------

class TestOllaBridgeToggle:
    """POST /settings/ollabridge — enable/disable the persona API at runtime."""

    def test_get_settings(self, client, mock_outbound):
        resp = client.get("/settings/ollabridge")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "enabled" in data

    def test_disable_blocks_endpoints(self, client, mock_outbound):
        # Disable
        resp = client.post("/settings/ollabridge", json={
            "enabled": False, "api_key": "",
        })
        assert resp.status_code == 200

        # Endpoints should return 503
        assert client.get("/v1/models").status_code == 503
        assert client.post("/v1/chat/completions", json={
            "model": "default",
            "messages": [{"role": "user", "content": "Hi"}],
        }).status_code == 503

        # Re-enable for other tests
        client.post("/settings/ollabridge", json={
            "enabled": True, "api_key": "",
        })

    def test_enable_restores_endpoints(self, client, mock_outbound):
        # Disable then re-enable
        client.post("/settings/ollabridge", json={"enabled": False, "api_key": ""})
        client.post("/settings/ollabridge", json={"enabled": True, "api_key": ""})
        assert client.get("/v1/models").status_code == 200

    def test_toggle_sets_api_key(self, client, mock_outbound):
        resp = client.post("/settings/ollabridge", json={
            "enabled": True, "api_key": "new-key-789",
        })
        data = resp.json()
        assert data["ok"] is True
        assert data["api_key_set"] is True

        # Clean up: unset key so other tests aren't affected
        client.post("/settings/ollabridge", json={
            "enabled": True, "api_key": "",
        })
