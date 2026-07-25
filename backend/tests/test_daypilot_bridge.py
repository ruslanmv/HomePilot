"""Tests for the DayPilot bridge (Batch A5).

Covers the pure protocol module (header parsing, propose-mode instruction,
directive extraction, capabilities document) and its wiring into the
OpenAI-compatible chat endpoint.
"""
import pytest

from app.daypilot_bridge import bridge as B


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------

class TestParseHeaders:
    def test_daypilot_client_activates_bridge(self):
        ctx = B.parse_bridge_headers(x_client_type="daypilot", tool_mode=None, session_id=None, bridge_version=None)
        assert ctx.active is True
        assert ctx.tool_mode == "propose" and ctx.propose is True

    def test_explicit_tool_mode_header_activates(self):
        ctx = B.parse_bridge_headers(x_client_type=None, tool_mode="propose", session_id="s1", bridge_version="1")
        assert ctx.active is True and ctx.session_id == "s1" and ctx.bridge_version == 1

    def test_ordinary_client_is_not_active(self):
        ctx = B.parse_bridge_headers(x_client_type="vr-chatbot", tool_mode=None, session_id=None, bridge_version=None)
        assert ctx.active is False

    def test_unknown_tool_mode_falls_back_to_propose(self):
        ctx = B.parse_bridge_headers(x_client_type="daypilot", tool_mode="execute-please", session_id=None, bridge_version=None)
        assert ctx.tool_mode == "propose"  # safe default; HomePilot never executes for DayPilot

    def test_blank_session_id_becomes_none(self):
        ctx = B.parse_bridge_headers(x_client_type="daypilot", tool_mode="propose", session_id="   ", bridge_version="x")
        assert ctx.session_id is None
        assert ctx.bridge_version == B.BRIDGE_VERSION  # non-int version falls back


# ---------------------------------------------------------------------------
# Directive extraction
# ---------------------------------------------------------------------------

class TestExtractDirectives:
    def _block(self, payload: str) -> str:
        return f"Sure, on it. [[DAYPILOT_DIRECTIVES]]{payload}[[/DAYPILOT_DIRECTIVES]]"

    def test_no_block_returns_content_unchanged(self):
        visible, directives = B.extract_directives("Just a normal reply.")
        assert visible == "Just a normal reply." and directives == []

    def test_task_create_directive(self):
        visible, directives = B.extract_directives(
            self._block('{"directives":[{"type":"task.create","title":"Draft Q3 report","priority":"high"}]}')
        )
        assert visible == "Sure, on it."  # machine block stripped
        assert directives == [{"type": "task.create", "title": "Draft Q3 report", "priority": "high"}]

    def test_action_propose_requires_valid_capability(self):
        _, ok = B.extract_directives(
            self._block('{"directives":[{"type":"daypilot.action.propose","capability":"email.send","summary":"Email Bob"}]}')
        )
        assert ok and ok[0]["capability"] == "email.send"
        _, bad = B.extract_directives(
            self._block('{"directives":[{"type":"daypilot.action.propose","capability":"launch.missiles","summary":"nope"}]}')
        )
        assert bad == []  # invalid capability dropped, reply preserved

    def test_unknown_directive_type_dropped(self):
        _, directives = B.extract_directives(
            self._block('{"directives":[{"type":"delete.everything"},{"type":"task.complete","ref":"t1"}]}')
        )
        assert [d["type"] for d in directives] == ["task.complete"]

    def test_malformed_json_preserves_reply(self):
        visible, directives = B.extract_directives(self._block("{not json"))
        assert visible == "Sure, on it." and directives == []

    def test_bare_list_payload_supported(self):
        _, directives = B.extract_directives(self._block('[{"type":"progress.report","percent":250}]'))
        assert directives[0]["percent"] == 100  # clamped to [0,100]

    def test_directive_cap_enforced(self):
        many = ",".join(['{"type":"task.create","title":"t"}'] * 30)
        _, directives = B.extract_directives(self._block(f'{{"directives":[{many}]}}'))
        assert len(directives) == B.MAX_DIRECTIVES_PER_TURN

    def test_code_fenced_block_tolerated(self):
        content = 'Done.\n```\n[[DAYPILOT_DIRECTIVES]]{"directives":[{"type":"task.create","title":"x"}]}[[/DAYPILOT_DIRECTIVES]]\n```'
        visible, directives = B.extract_directives(content)
        assert "DAYPILOT_DIRECTIVES" not in visible
        assert directives and directives[0]["type"] == "task.create"


# ---------------------------------------------------------------------------
# Propose suffix + capabilities document
# ---------------------------------------------------------------------------

class TestBridgeMetadata:
    def test_propose_suffix_mentions_contract(self):
        s = B.propose_system_suffix()
        assert "propose" in s.lower() and "DAYPILOT_DIRECTIVES" in s
        assert "CANNOT" in s  # the persona must not act on the outside world itself

    def test_capabilities_document_shape(self):
        doc = B.capabilities_document()
        assert doc["bridge_version"] == B.BRIDGE_VERSION
        assert "propose" in doc["tool_modes"]
        assert "task.create" in doc["directives"]
        assert "email.send" in doc["capabilities"]
        assert doc["headers"]["tool_mode"] == "X-HomePilot-Tool-Mode"


# ---------------------------------------------------------------------------
# Endpoint wiring
# ---------------------------------------------------------------------------

class TestBridgeEndpoint:
    def _headers(self):
        return {
            "X-Client-Type": "daypilot",
            "X-HomePilot-Tool-Mode": "propose",
            "X-HomePilot-Session-ID": "sess-abc",
            "X-HomePilot-Bridge-Version": "1",
        }

    def test_capabilities_endpoint(self, client, mock_outbound):
        resp = client.get("/v1/integrations/daypilot/capabilities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["default_tool_mode"] == "propose"
        assert "x_directives" in data["response_fields"]

    def test_bridge_client_gets_correlation_fields(self, client, mock_outbound):
        resp = client.post(
            "/v1/chat/completions",
            headers=self._headers(),
            json={"model": "personality:assistant", "messages": [{"role": "user", "content": "Hi"}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Even with no proposal this turn, the bridge fields are present.
        assert data["x_homepilot"]["session_id"] == "sess-abc"
        assert data["x_homepilot"]["tool_mode"] == "propose"
        assert data["x_directives"]["items"] == []

    def test_non_bridge_client_has_no_bridge_fields(self, client, mock_outbound):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "personality:assistant", "messages": [{"role": "user", "content": "Hi"}]},
        )
        assert resp.status_code == 200
        assert "x_homepilot" not in resp.json()
