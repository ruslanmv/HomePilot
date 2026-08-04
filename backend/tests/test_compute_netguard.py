"""Security — SSRF guard for custom compute endpoints."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


def test_netguard_allows_legit_and_blocks_dangerous():
    from app.compute.netguard import is_safe_outbound_url as safe
    # Legit: hosted APIs, and self-hosted loopback/LAN GPU nodes.
    assert safe("https://api.groq.com/openai/v1")
    assert safe("http://localhost:11434")
    assert safe("http://192.168.1.50:8000")
    assert safe("http://10.0.0.4:8188")
    assert safe(None)  # nothing to dial
    # Dangerous: cloud metadata, link-local, non-http schemes, no host.
    assert not safe("http://169.254.169.254/latest/meta-data/")
    assert not safe("http://metadata.google.internal/")
    assert not safe("http://[fe80::1]/")
    assert not safe("file:///etc/passwd")
    assert not safe("ftp://host/x")
    assert not safe("http://")


def test_block_private_env_tightens_policy(monkeypatch):
    from app.compute import netguard
    monkeypatch.setenv("HOMEPILOT_COMPUTE_BLOCK_PRIVATE", "true")
    # With the strict flag, private/loopback are refused too.
    assert netguard.is_safe_outbound_url("http://10.0.0.4:8000") is False
    assert netguard.is_safe_outbound_url("http://localhost:11434") is False
    # Public still fine.
    assert netguard.is_safe_outbound_url("https://api.groq.com") is True


def test_admin_source_create_rejects_metadata_url(client):
    r = client.post("/compute/admin/sources", json={
        "id": "evil", "name": "evil", "kind": "openai_compatible",
        "base_url": "http://169.254.169.254/latest/meta-data/",
    })
    assert r.status_code == 400
    assert "metadata" in r.text.lower() or "blocked" in r.text.lower()
    # It was not persisted.
    listed = client.get("/compute/admin/sources").json()["sources"]
    assert not any(s["id"] == "evil" for s in listed)


def test_admin_source_test_refuses_blocked_url(client):
    # A source that somehow holds a blocked URL is not dialed.
    client.post("/compute/admin/sources", json={
        "id": "vllm-ok", "name": "vLLM", "kind": "openai_compatible",
        "base_url": "http://10.0.0.9:8000",
    })
    # Re-point it to a blocked URL directly via the registry, then test().
    from app.compute import registry
    src = registry.get_source("vllm-ok")
    src.base_url = "http://169.254.169.254"
    registry.upsert_source(src)
    r = client.post("/compute/admin/sources/vllm-ok/test").json()
    assert r["ok"] is False and ("blocked" in r["reason"].lower() or "metadata" in r["reason"].lower())
    client.delete("/compute/admin/sources/vllm-ok")
