# backend/tests/test_topology_health.py
"""
Topology Health Tests — CI-safe, no network, no LLM required.

Validates that all 4 topologies are importable, structurally correct,
and their endpoints respond. Uses mocked outbound HTTP from conftest.

Usage:
  cd backend && python -m pytest tests/test_topology_health.py -v

Topology map:
  T1 = Basic Chat           (/chat)
  T2 = Project-Scoped RAG   (/projects, /chat with project_id)
  T3 = Agent Tool Use        (/v1/agent/chat)
  T4 = Multimodal Knowledge  (image upload + knowledge search)
"""
import json
import sys
from pathlib import Path

import pytest


# ===================================================================
# T1: Basic Chat — health
# ===================================================================

class TestTopology1BasicChat:
    """T1: Direct LLM chat works and returns expected structure."""

    def test_chat_endpoint_exists(self, client):
        """POST /chat should be routable (not 404/405)."""
        r = client.post("/chat", json={"message": "ping"})
        assert r.status_code != 404, "POST /chat route missing"
        assert r.status_code != 405, "POST /chat method not allowed"

    def test_chat_returns_text(self, client, mock_outbound):
        """POST /chat returns conversation_id + text + media keys."""
        r = client.post("/chat", json={
            "message": "hello",
            "conversation_id": "t1-health",
            "mode": "chat",
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert "conversation_id" in data
        assert "text" in data
        assert isinstance(data["text"], str)
        assert "media" in data

    def test_health_endpoint(self, client):
        """GET /health returns ok=true."""
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["ok"] is True


# ===================================================================
# T2: Project-Scoped Knowledge (RAG) — health
# ===================================================================

class TestTopology2ProjectRAG:
    """T2: Project creation + knowledge base + scoped chat."""

    def test_projects_endpoint_exists(self, client):
        """GET /projects should be routable."""
        r = client.get("/projects")
        assert r.status_code in (200, 401)

    def test_create_and_get_project(self, client, mock_outbound):
        """Can create a project and retrieve it."""
        r = client.post("/projects", json={
            "name": "T2 Health Test",
            "description": "test project",
            "instructions": "be helpful",
        })
        assert r.status_code in (200, 201), r.text
        data = r.json()
        assert data["ok"] is True
        pid = data["project"]["id"]

        r2 = client.get(f"/projects/{pid}")
        assert r2.status_code == 200
        assert r2.json()["ok"] is True

    def test_vectordb_module_importable(self):
        """vectordb module loads without error."""
        from app.vectordb import (
            CHROMADB_AVAILABLE,
            query_project_knowledge,
            get_project_document_count,
            chunk_text,
        )
        # chunk_text should work standalone (no DB needed)
        chunks = chunk_text("Hello world. " * 100)
        assert len(chunks) >= 1

    def test_knowledge_query_empty_project(self):
        """Querying an empty project returns empty list, not an error."""
        from app.vectordb import query_project_knowledge, CHROMADB_AVAILABLE
        if not CHROMADB_AVAILABLE:
            pytest.skip("ChromaDB not installed")
        results = query_project_knowledge("nonexistent-project", "test query")
        assert isinstance(results, list)


# ===================================================================
# T3: Agent-Controlled Tool Use — health
# ===================================================================

class TestTopology3AgentToolUse:
    """T3: Agent loop, tool registry, and endpoint."""

    def test_agent_endpoint_exists(self, client, mock_outbound):
        """POST /v1/agent/chat should be routable."""
        r = client.post("/v1/agent/chat", json={"message": "ping"})
        assert r.status_code != 404, "POST /v1/agent/chat route missing"
        assert r.status_code != 405, "POST /v1/agent/chat method not allowed"

    def test_agent_chat_returns_structure(self, client, mock_outbound):
        """Agent endpoint returns conversation_id + text + agent metadata."""
        r = client.post("/v1/agent/chat", json={
            "message": "what is 2+2?",
            "conversation_id": "t3-health",
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert "conversation_id" in data
        assert "text" in data
        assert "agent" in data
        assert "tool_calls_used" in data["agent"]
        assert "tools_invoked" in data["agent"]

    def test_tool_registry_has_all_tools(self):
        """TOOL_REGISTRY should contain all 6 expected tools."""
        from app.agent_chat import TOOL_REGISTRY
        expected = {
            "vision.analyze",
            "knowledge.search",
            "memory.recall",
            "web.search",
            "image.index",
            "memory.store",
        }
        assert expected.issubset(set(TOOL_REGISTRY.keys())), (
            f"Missing tools: {expected - set(TOOL_REGISTRY.keys())}"
        )

    def test_system_prompt_includes_tools(self):
        """Agent system prompt should mention all registered tools."""
        from app.agent_chat import _build_agent_system_prompt
        prompt = _build_agent_system_prompt()
        assert "vision.analyze" in prompt
        assert "knowledge.search" in prompt
        assert "memory.recall" in prompt
        assert "web.search" in prompt
        assert "image.index" in prompt
        assert "memory.store" in prompt

    def test_json_parser_valid(self):
        """JSON extractor handles well-formed and malformed input."""
        from app.agent_chat import _extract_json_obj
        # Valid
        obj = _extract_json_obj('{"type": "final", "text": "hello"}')
        assert obj == {"type": "final", "text": "hello"}
        # Embedded in text
        obj2 = _extract_json_obj('Some text {"type": "final", "text": "ok"} more text')
        assert obj2["type"] == "final"
        # Invalid
        assert _extract_json_obj("not json") is None
        assert _extract_json_obj("") is None
        assert _extract_json_obj(None) is None

    def test_format_tool_context(self):
        """Tool context formatter produces expected output."""
        from app.agent_chat import _format_tool_context
        ctx = _format_tool_context("test.tool", "result text", meta={"key": "val"})
        assert "TOOL_RESULT" in ctx
        assert "tool=test.tool" in ctx
        assert "result text" in ctx


# ===================================================================
# T4: Multimodal Knowledge RAG — health
# ===================================================================

class TestTopology4MultimodalKnowledge:
    """T4: Image indexing pipeline + extended upload."""

    def test_vectordb_images_importable(self):
        """vectordb_images module loads without error."""
        from app.vectordb_images import (
            is_image_file,
            IMAGE_EXTENSIONS,
            index_image_to_knowledge,
            index_image_from_url,
        )
        assert len(IMAGE_EXTENSIONS) >= 4

    def test_is_image_file(self):
        """Image extension detection works for common formats."""
        from app.vectordb_images import is_image_file
        assert is_image_file("photo.png") is True
        assert is_image_file("photo.jpg") is True
        assert is_image_file("photo.jpeg") is True
        assert is_image_file("photo.webp") is True
        assert is_image_file("doc.pdf") is False
        assert is_image_file("readme.md") is False
        assert is_image_file("data.txt") is False

    def test_upload_accepts_images(self, client, mock_outbound):
        """Project upload endpoint should accept image files (not reject as invalid type)."""
        # Create a project first
        r = client.post("/projects", json={
            "name": "T4 Image Test",
            "description": "test",
            "instructions": "test",
        })
        assert r.status_code in (200, 201), r.text
        pid = r.json()["project"]["id"]

        # Upload a tiny PNG (1x1 pixel)
        import io
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00'
            b'\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00'
            b'\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        r2 = client.post(
            f"/projects/{pid}/upload",
            files={"file": ("test.png", io.BytesIO(png_bytes), "image/png")},
        )
        # May fail on vision analysis (mocked Ollama), but should NOT be 400 "invalid file type"
        assert r2.status_code != 400 or "invalid_file_type" not in r2.text, (
            "Image upload rejected as invalid file type — T4 extension not working"
        )

    def test_image_index_tool_in_agent(self):
        """image.index should be in the agent tool registry."""
        from app.agent_chat import TOOL_REGISTRY
        assert "image.index" in TOOL_REGISTRY

    def test_memory_v2_importable(self):
        """Memory V2 module loads and singleton works."""
        from app.memory_v2 import get_memory_v2, V2Config
        engine = get_memory_v2()
        assert engine is not None
        assert isinstance(engine.cfg, V2Config)
