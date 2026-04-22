import importlib

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client():
    routes_mod = importlib.import_module("app.expert.routes")
    app = FastAPI()
    app.include_router(routes_mod.router)
    return TestClient(app), routes_mod


def test_ollabridge_adapter_returns_openai_shape(monkeypatch):
    client, routes_mod = _client()

    async def fake_expert_chat(req):
        return routes_mod.ExpertChatResponse(
            content="adapter-response",
            provider_used="local",
            model_used="llama3",
            complexity_score=2,
            thinking_mode_used="fast",
        )

    monkeypatch.setattr(routes_mod, "expert_chat", fake_expert_chat)

    r = client.post(
        "/v1/expert/ollabridge/chat/completions",
        json={
            "messages": [{"role": "user", "content": "hello expert"}],
            "provider": "auto",
            "thinking_mode": "auto",
        },
    )

    assert r.status_code == 200
    data = r.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["content"] == "adapter-response"


def test_persona_draft_endpoint_generates_payload(monkeypatch):
    client, routes_mod = _client()

    async def fake_expert_chat(req):
        return routes_mod.ExpertChatResponse(
            content="You are a medical research persona.",
            provider_used="local",
            model_used="llama3",
            complexity_score=6,
            thinking_mode_used="think",
        )

    monkeypatch.setattr(routes_mod, "expert_chat", fake_expert_chat)

    r = client.post(
        "/v1/expert/persona/draft",
        json={
            "mission": "Create a healthcare research assistant persona",
            "domain": "medicine",
            "tone": "professional",
            "constraints": ["must cite sources"],
        },
    )

    assert r.status_code == 200
    body = r.json()
    assert "Research Persona" in body["name"]
    assert body["provider_used"] == "local"
    assert "retrieval" in body["suggested_tools"]


def test_mcp_plan_endpoint_returns_catalog(monkeypatch):
    client, _ = _client()
    monkeypatch.setenv("CONTEXT_FORGE_URL", "http://forge:4444")
    r = client.get("/v1/expert/mcp/plan")
    assert r.status_code == 200
    body = r.json()
    assert body["orchestrator"] == "context_forge"
    assert "tool_mapping" in body
    assert body["tool_mapping"]["web_search"] == "mcp-web-search"
    assert any(server["key"] == "mcp-web-search" and server["forge_tool_id"] == "mcp_web_search" for server in body["servers"])
