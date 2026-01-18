"""
Comprehensive test suite for HomePilot APIs with mocks.

Tests all endpoints to ensure they work correctly even when external services are down.
"""

import pytest
from unittest.mock import patch, MagicMock
import json


def test_health_basic(client, mock_outbound):
    """Test basic health endpoint."""
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert data.get("service") == "homepilot-backend"


def test_health_detailed(client, mock_outbound):
    """Test detailed health endpoint with all service checks."""
    r = client.get("/health/detailed")
    assert r.status_code in [200, 503]  # May be 503 if services are down
    data = r.json()
    assert "services" in data
    assert "ollama" in data["services"]
    assert "comfyui" in data["services"]
    assert "llm" in data["services"]


@patch("app.main.httpx.AsyncClient")
def test_models_ollama_success(mock_client_class, client, mock_outbound):
    """Test /models endpoint when Ollama is running."""
    # Mock Ollama response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "models": [
            {"name": "llama3.1:latest"},
            {"name": "llama3:latest"},
            {"name": "gemma:2b"},
        ]
    }

    mock_client = MagicMock()
    mock_client.__aenter__.return_value.get.return_value = mock_response
    mock_client_class.return_value = mock_client

    r = client.get("/models?provider=ollama")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["provider"] == "ollama"
    assert len(data["models"]) == 3
    assert "llama3.1:latest" in data["models"]


@patch("app.main.httpx.AsyncClient")
def test_models_ollama_down(mock_client_class, client, mock_outbound):
    """Test /models endpoint when Ollama is down."""
    # Mock Ollama connection error
    mock_client = MagicMock()
    mock_client.__aenter__.return_value.get.side_effect = Exception("Connection refused")
    mock_client_class.return_value = mock_client

    r = client.get("/models?provider=ollama")
    assert r.status_code in [500, 503]  # May be 500 or 503 depending on error handling
    data = r.json()
    assert data["ok"] is False


@patch("app.orchestrator.llm_chat")
def test_chat_basic(mock_llm, client, mock_outbound):
    """Test /chat endpoint with mocked LLM."""
    # Mock LLM response
    mock_llm.return_value = {
        "choices": [
            {
                "message": {
                    "content": "Hello! How can I help you today?"
                }
            }
        ]
    }

    r = client.post("/chat", json={
        "message": "hello",
        "mode": "chat"
    })

    assert r.status_code == 200
    data = r.json()
    assert "conversation_id" in data
    assert "text" in data
    assert "Hello" in data["text"]


@patch("app.orchestrator.llm_chat")
def test_chat_ollama_provider(mock_llm, client, mock_outbound):
    """Test /chat endpoint with Ollama provider."""
    mock_llm.return_value = {
        "choices": [
            {
                "message": {
                    "content": "Response from Ollama"
                }
            }
        ]
    }

    r = client.post("/chat", json={
        "message": "test message",
        "mode": "chat",
        "provider": "ollama",
        "ollama_base_url": "http://localhost:11434",
        "ollama_model": "llama3.1:latest"
    })

    assert r.status_code == 200
    data = r.json()
    assert data["text"] == "Response from Ollama"


@patch("app.orchestrator.run_workflow")
@patch("app.orchestrator.llm_chat")
def test_chat_imagine_mode(mock_llm, mock_workflow, client, mock_outbound):
    """Test /chat endpoint in imagine mode."""
    # Mock prompt refiner
    mock_llm.return_value = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "prompt": "A beautiful sunset over the ocean",
                        "negative_prompt": "blurry, low quality",
                        "aspect_ratio": "16:9",
                        "style": "photorealistic"
                    })
                }
            }
        ]
    }

    # Mock ComfyUI workflow
    mock_workflow.return_value = {
        "images": ["http://localhost:8000/files/image1.png"]
    }

    r = client.post("/chat", json={
        "message": "imagine a sunset",
        "mode": "imagine",
        "provider": "ollama"
    })

    assert r.status_code == 200
    data = r.json()
    assert "media" in data
    if data["media"]:
        assert "images" in data["media"]


def test_chat_missing_message(client, mock_outbound):
    """Test /chat endpoint with missing message."""
    r = client.post("/chat", json={})
    assert r.status_code == 422  # Validation error


def test_providers_endpoint(client, mock_outbound):
    """Test /providers endpoint."""
    r = client.get("/providers")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "available" in data
    assert "providers" in data


def test_settings_endpoint(client, mock_outbound):
    """Test /settings endpoint."""
    r = client.get("/settings")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "default_provider" in data
    assert "llm_base_url" in data


def test_upload_endpoint(client, mock_outbound):
    """Test /upload endpoint."""
    # Create a mock file
    file_content = b"fake image content"
    files = {"file": ("test.png", file_content, "image/png")}

    r = client.post("/upload", files=files)
    assert r.status_code in [200, 201]
    data = r.json()
    assert "url" in data


def test_cors_headers(client, mock_outbound):
    """Test that CORS headers are present."""
    r = client.options("/health", headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET"
    })
    # Should not fail and should have CORS headers
    assert "access-control-allow-origin" in [h.lower() for h in r.headers.keys()]


@patch("app.orchestrator.llm_chat")
def test_chat_error_handling(mock_llm, client, mock_outbound):
    """Test /chat endpoint handles errors gracefully."""
    # Mock LLM error
    mock_llm.side_effect = Exception("LLM connection failed")

    r = client.post("/chat", json={
        "message": "test",
        "mode": "chat"
    })

    assert r.status_code == 200  # Should still return 200 with error message
    data = r.json()
    assert "error" in data["text"].lower() or "llm" in data["text"].lower()


def test_models_unsupported_provider(client, mock_outbound):
    """Test /models with unsupported provider."""
    r = client.get("/models?provider=unknown")
    assert r.status_code == 400
    data = r.json()
    assert data["ok"] is False
    assert "not supported" in data.get("message", "").lower()
