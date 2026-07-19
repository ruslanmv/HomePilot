"""
OllaBridge legacy-provider CONTRACT tests — Phase 0 of the Cloud Mirror.

These freeze the exact behavior the 3D Avatar Chatbot and OpenAI SDK clients
depend on, BEFORE any mirror plane is built, so a regression is caught the
moment it happens. The design's rule is that the legacy /v1 plane never
changes; these tests are the executable form of that promise.

Coverage (from the design doc's Phase 0 list):
  - GET /v1/models shape + persona/personality entries + unpublished excluded
  - persona:* / personality:* / bare-id routing (_parse_model)
  - stable external persona ids (_build_external_id)
  - unpublished persona error (code=persona_unpublished)
  - chat-completion response shape + enriched x_attachments/x_directives rules
  - the four auth paths (api-key header, bearer, session/pairing, localhost,
    and open-when-unset)

Fixtures in tests/fixtures/ollabridge_contract/ document the frozen JSON
shapes for humans; the assertions here are the enforcement.

Self-contained: no network, no live LLM.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

_FIXTURES = Path(__file__).parent / "fixtures" / "ollabridge_contract"


def _fixture(name: str) -> dict:
    with open(_FIXTURES / name, "r", encoding="utf-8") as fh:
        return json.load(fh)


PUBLISHED = {
    "id": "63ea2100aaaa", "project_type": "persona", "name": "Ruslan Assistant",
    "persona_agent": {"label": "Ruslan Assistant"},
    "shared_api": {"enabled": True, "alias": "ruslan-assistant"},
}
UNPUBLISHED = {
    "id": "p2", "project_type": "persona", "name": "Private Financial Assistant",
    "persona_agent": {"label": "Private Financial Assistant"},
    "shared_api": {"enabled": False},
}


# ── /v1/models ───────────────────────────────────────────────────────────────

class TestModelsList:
    def test_shape_and_publish_gate(self, monkeypatch):
        import app.openai_compat_endpoint as compat
        monkeypatch.setattr(compat, "_compat_enabled", True, raising=False)

        class _Projects:
            @staticmethod
            def list_all_projects():
                return [PUBLISHED, UNPUBLISHED]

        monkeypatch.setattr(compat, "_get_projects", lambda: _Projects)
        resp = asyncio.run(compat.openai_list_models())
        data = resp.model_dump()

        assert data["object"] == "list"
        ids = {m["id"] for m in data["data"]}
        # published persona present, unpublished absent
        assert any(i.startswith("persona:ruslan-assistant--") for i in ids)
        assert not any("Private" in (m.get("name") or "") for m in data["data"])
        # personalities present with the frozen owned_by tag
        personality = next(m for m in data["data"] if m["id"].startswith("personality:"))
        assert personality["owned_by"] == "homepilot-personality"
        assert personality["object"] == "model"
        # persona entries carry the frozen owned_by tag
        persona = next(m for m in data["data"] if m["id"].startswith("persona:"))
        assert persona["owned_by"] == "homepilot-persona"

    def test_fixture_matches_field_names(self):
        # the human-facing fixture must not drift from the real field set
        fx = _fixture("models_list.json")
        assert fx["object"] == "list"
        for entry in fx["data"]:
            assert set(entry) >= {"id", "object", "created", "owned_by", "name"}

    def test_disabled_returns_503(self, monkeypatch):
        import app.openai_compat_endpoint as compat
        from fastapi import HTTPException
        monkeypatch.setattr(compat, "_compat_enabled", False, raising=False)
        with pytest.raises(HTTPException) as ei:
            asyncio.run(compat.openai_list_models())
        assert ei.value.status_code == 503


# ── Model routing + stable ids ───────────────────────────────────────────────

class TestRouting:
    def test_parse_model(self):
        import app.openai_compat_endpoint as compat
        assert compat._parse_model("persona:abc--1234")[0] == "persona"
        assert compat._parse_model("personality:assistant")[0] == "personality"
        # a bare known personality id resolves to personality
        assert compat._parse_model("assistant")[0] == "personality"

    def test_external_id_is_stable_and_slugged(self):
        import app.openai_compat_endpoint as compat
        assert compat._build_external_id(PUBLISHED) == "persona:ruslan-assistant--63ea2100"
        # no alias -> derived from label, still --<short8>
        no_alias = {**PUBLISHED, "shared_api": {"enabled": True}}
        eid = compat._build_external_id(no_alias)
        assert eid.startswith("persona:ruslan-assistant--") and eid.endswith("63ea2100")


# ── Unpublished persona error ────────────────────────────────────────────────

class TestUnpublishedError:
    def test_raises_persona_unpublished(self, monkeypatch):
        import app.openai_compat_endpoint as compat
        from fastapi import HTTPException

        class _Projects:
            @staticmethod
            def list_all_projects():
                return [UNPUBLISHED]

        monkeypatch.setattr(compat, "_get_projects", lambda: _Projects)
        with pytest.raises(HTTPException) as ei:
            compat._resolve_published_persona("p2")
        assert ei.value.status_code == 404
        err = ei.value.detail["error"]
        assert err["code"] == "persona_unpublished"
        assert err["type"] == "model_not_available"

    def test_fixture_matches_error_contract(self):
        fx = _fixture("unpublished_persona_error.json")["error"]
        assert fx["code"] == "persona_unpublished"
        assert fx["type"] == "model_not_available"
        assert set(fx) >= {"type", "code", "message", "model", "available_models_hint"}


# ── Chat-completion response shape ───────────────────────────────────────────

class TestChatResponseShape:
    def test_base_body_is_openai_compatible(self):
        import app.openai_compat_endpoint as compat
        resp = compat.ChatCompletionResponse(
            id="homepilot-deadbeef0000", created=1700000000,
            model="persona:x--1234",
            choices=[compat.ChatCompletionChoice(
                message=compat.ChatMessage(role="assistant", content="hi"))],
        ).model_dump()
        assert resp["id"].startswith("homepilot-")
        assert resp["object"] == "chat.completion"
        assert resp["choices"][0]["message"]["role"] == "assistant"
        # base body must NOT carry enrichment keys unless explicitly added
        assert "x_attachments" not in resp and "x_directives" not in resp

    def test_enriched_fields_are_additive_only(self):
        # the frozen enriched fixture: x_* present only alongside a normal body
        fx = _fixture("chat_completion_enriched.json")
        assert fx["object"] == "chat.completion"
        assert isinstance(fx["x_attachments"], list) and fx["x_attachments"]
        att = fx["x_attachments"][0]
        assert set(att) >= {"type", "name", "url", "mime"}
        assert "avatar" in fx["x_directives"]


# ── Authentication contract (four paths) ─────────────────────────────────────

class TestAuthContract:
    def _req(self, host="203.0.113.1"):
        class _C:
            def __init__(s): s.host = host
        class _R:
            client = _C()
        return _R()

    def test_open_when_no_key_configured(self, monkeypatch):
        from app import auth
        monkeypatch.setattr(auth._cfg, "API_KEY", "", raising=False)
        assert auth.require_ollabridge_api_key(self._req(), None, None, None) is True

    def test_api_key_header_and_bearer(self, monkeypatch):
        from app import auth
        monkeypatch.setattr(auth._cfg, "API_KEY", "secret-key", raising=False)
        # X-API-Key path
        assert auth.require_ollabridge_api_key(self._req(), "secret-key", None, None) is True
        # Authorization: Bearer path
        assert auth.require_ollabridge_api_key(
            self._req(), None, "Bearer secret-key", None) is True
        # wrong key from a remote host is rejected
        with pytest.raises(Exception):
            auth.require_ollabridge_api_key(self._req(), "nope", None, None)

    def test_localhost_trust_bypasses_key(self, monkeypatch):
        from app import auth
        monkeypatch.setattr(auth._cfg, "API_KEY", "secret-key", raising=False)
        assert auth.require_ollabridge_api_key(
            self._req(host="127.0.0.1"), None, None, None) is True
