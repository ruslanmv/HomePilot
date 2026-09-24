"""
agentic.invoke node job (HP-1) — additive, flag-gated, allow-listed.

Locks:
  - flag off: operation not registered; job whitelist, /operations and the
    manifest capabilities are unchanged
  - deny by default: empty allow-list rejects every tool
  - allow-listed tools run through Context Forge (faked here) and results
    are unwrapped from JSON-RPC / MCP content
  - honest failures with stable codes; arguments are never logged

Self-contained: fake Forge client, no network.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import time

import pytest

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


class _FakeReq:
    def __init__(self, host="127.0.0.1"):
        class _C:
            def __init__(s):
                s.host = host

        self.client = _C()


class _FakeForge:
    def __init__(self, result=None, tools=None):
        self.result = result if result is not None else {
            "jsonrpc": "2.0",
            "id": "1",
            "result": {"content": [{"type": "text", "text": '{"outfits": [{"id": "o1"}]}'}]},
        }
        self.tools = tools or []
        self.calls = []

    async def list_tools(self, timeout=5.0):
        return self.tools

    async def invoke_tool(self, tool_id, args, timeout=30.0):
        self.calls.append((tool_id, args, timeout))
        return self.result


def _load(monkeypatch, tmp_path, *, mcp: bool, allowed: str = ""):
    monkeypatch.setenv("HOMEPILOT_MIRROR_JOBS_ENABLED", "true")
    monkeypatch.setenv("NODE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("NODE_MANIFEST_STATE_PATH", str(tmp_path / "rev.json"))
    monkeypatch.setenv("HOMEPILOT_MIRROR_MCP_ENABLED", "true" if mcp else "false")
    monkeypatch.setenv("HOMEPILOT_MIRROR_ALLOWED_TOOLS", allowed)
    import app.node_ops_agentic as ops
    import app.node_jobs as jobs

    importlib.reload(ops)
    importlib.reload(jobs)
    return jobs, ops


def _wait(job, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end and job.status not in ("completed", "failed", "cancelled"):
        time.sleep(0.01)


# ── flag off: nothing changes ───────────────────────────────────────


def test_flag_off_does_not_register(monkeypatch, tmp_path):
    jobs, ops = _load(monkeypatch, tmp_path, mcp=False, allowed="*")
    names = [o["operation"] for o in jobs.available_operations()]
    assert names == ["chat.completions", "images.generate", "videos.generate"]
    assert ops.manifest_capabilities() == []
    with pytest.raises(KeyError):
        jobs.create_job("agentic.invoke", {"tool": "hp.smartmirror.style_suggest"})
    resp = jobs.create_node_job(
        jobs.JobCreateRequest(operation="agentic.invoke", params={}), _FakeReq()
    )
    assert resp.status_code == 400


def test_flag_off_manifest_capabilities_unchanged(monkeypatch, tmp_path):
    _load(monkeypatch, tmp_path, mcp=False)
    import app.node_manifest as manifest

    caps = manifest._capabilities({"mcp": {"status": "ready"}})
    assert "agentic.invoke" not in caps
    assert "mcp.invoke" in caps


def test_flag_on_registers_with_scope_and_manifest(monkeypatch, tmp_path):
    jobs, ops = _load(monkeypatch, tmp_path, mcp=True)
    assert {"operation": "agentic.invoke", "scope": "mcp:invoke"} in jobs.available_operations()
    import app.node_manifest as manifest

    assert "agentic.invoke" in manifest._capabilities({})


# ── allow-list ──────────────────────────────────────────────────────


def test_allow_list_is_deny_by_default_and_glob_based(monkeypatch, tmp_path):
    _, ops = _load(monkeypatch, tmp_path, mcp=True, allowed="")
    assert not ops.tool_allowed("hp.smartmirror.style_suggest")
    _, ops = _load(monkeypatch, tmp_path, mcp=True, allowed="hp.smartmirror.*, hp.weather.today")
    assert ops.tool_allowed("hp.smartmirror.style_suggest")
    assert ops.tool_allowed("hp.weather.today")
    assert not ops.tool_allowed("hp.homepilot.shell_exec")
    assert not ops.tool_allowed("HP.SMARTMIRROR.style_suggest")


def test_disallowed_tool_fails_honestly(monkeypatch, tmp_path):
    jobs, ops = _load(monkeypatch, tmp_path, mcp=True, allowed="hp.smartmirror.*")
    fake = _FakeForge()
    monkeypatch.setattr(ops, "_forge_client", lambda: fake)
    job = jobs.create_job("agentic.invoke", {"tool": "hp.homepilot.shell_exec", "arguments": {}})
    _wait(job)
    assert job.status == "failed"
    assert "TOOL_NOT_ALLOWED" in job.error
    assert job.output is None
    assert fake.calls == []


@pytest.mark.parametrize("tool", ["", "../etc", "a b", None, 42])
def test_invalid_tool_names_rejected(monkeypatch, tmp_path, tool):
    jobs, ops = _load(monkeypatch, tmp_path, mcp=True, allowed="*")
    monkeypatch.setattr(ops, "_forge_client", lambda: _FakeForge())
    job = jobs.create_job("agentic.invoke", {"tool": tool})
    _wait(job)
    assert job.status == "failed"
    assert "TOOL_NOT_ALLOWED" in job.error


# ── execution ───────────────────────────────────────────────────────


def test_allowed_tool_runs_and_result_is_unwrapped(monkeypatch, tmp_path, caplog):
    jobs, ops = _load(monkeypatch, tmp_path, mcp=True, allowed="hp.smartmirror.*")
    fake = _FakeForge(tools=[{"name": "smartmirror-hp-smartmirror-style-suggest"}])
    monkeypatch.setattr(ops, "_forge_client", lambda: fake)
    caplog.set_level(logging.INFO, logger="homepilot.node_ops_agentic")

    secret = "a private prompt"
    job = jobs.create_job(
        "agentic.invoke",
        {"tool": "hp.smartmirror.style_suggest", "arguments": {"prompt": secret}, "timeout_s": 500},
    )
    _wait(job)
    assert job.status == "completed", job.error
    assert job.output == {"tool": "hp.smartmirror.style_suggest", "result": {"outfits": [{"id": "o1"}]}}
    # Resolved to the gateway-prefixed Forge name; timeout clamped.
    assert fake.calls == [("smartmirror-hp-smartmirror-style-suggest", {"prompt": secret}, 120.0)]
    assert "hp.smartmirror.style_suggest" in caplog.text
    assert secret not in caplog.text


def test_tool_error_fails_without_fabricating(monkeypatch, tmp_path):
    jobs, ops = _load(monkeypatch, tmp_path, mcp=True, allowed="*")
    monkeypatch.setattr(ops, "_forge_client", lambda: _FakeForge(result={"error": "Could not invoke tool x"}))
    job = jobs.create_job("agentic.invoke", {"tool": "hp.smartmirror.job_get", "arguments": {}})
    _wait(job)
    assert job.status == "failed"
    assert "TOOL_FAILED" in job.error
    assert job.output is None


def test_arguments_must_be_an_object(monkeypatch, tmp_path):
    jobs, ops = _load(monkeypatch, tmp_path, mcp=True, allowed="*")
    monkeypatch.setattr(ops, "_forge_client", lambda: _FakeForge())
    job = jobs.create_job("agentic.invoke", {"tool": "hp.x", "arguments": ["nope"]})
    _wait(job)
    assert job.status == "failed"
    assert "arguments must be an object" in job.error


def test_endpoint_creates_job_on_localhost(monkeypatch, tmp_path):
    jobs, ops = _load(monkeypatch, tmp_path, mcp=True, allowed="hp.smartmirror.*")
    monkeypatch.setattr(ops, "_forge_client", lambda: _FakeForge())
    created = jobs.create_node_job(
        jobs.JobCreateRequest(
            operation="agentic.invoke",
            params={"tool": "hp.smartmirror.wardrobe_list", "arguments": {"profile_id": "p1"}},
        ),
        _FakeReq(),
    )
    assert created["operation"] == "agentic.invoke"
    job = jobs.get_job(created["job_id"])
    _wait(job)
    assert jobs.get_node_job(job.id, _FakeReq())["status"] == "completed"
    # Remote callers are still refused by the shared guard.
    assert jobs.create_node_job(
        jobs.JobCreateRequest(operation="agentic.invoke", params={}), _FakeReq("10.0.0.9")
    ).status_code == 403


# ── helpers ─────────────────────────────────────────────────────────


def test_resolve_tool_name(monkeypatch, tmp_path):
    _, ops = _load(monkeypatch, tmp_path, mcp=True)
    assert ops.resolve_tool_name("hp.a.b", []) == "hp.a.b"
    assert ops.resolve_tool_name("hp.a.b", [{"name": "hp.a.b"}]) == "hp.a.b"
    assert ops.resolve_tool_name("hp.a.b", [{"name": "gw-x", "originalName": "hp.a.b"}]) == "gw-x"
    assert ops.resolve_tool_name("hp.smartmirror.job_get", [{"name": "smartmirror-hp-smartmirror-job-get"}]) == (
        "smartmirror-hp-smartmirror-job-get"
    )
    assert ops.resolve_tool_name("hp.a.b", [{"name": "other"}]) == "hp.a.b"


def test_normalize_result(monkeypatch, tmp_path):
    _, ops = _load(monkeypatch, tmp_path, mcp=True)
    assert ops.normalize_result({"result": {"structuredContent": {"a": 1}}}) == {"a": 1}
    assert ops.normalize_result({"result": {"content": [{"type": "text", "text": "hello"}]}}) == {"text": "hello"}
    assert ops.normalize_result({"result": {"content": [{"type": "text", "text": "[1, 2]"}]}}) == [1, 2]
    assert ops.normalize_result({"items": []}) == {"items": []}
