"""PR 1 foundation — modality-specific health + ComputeRouter seam.

Proves the two behaviours this PR adds:

  * Local health is per-modality: chat asks Ollama, image asks ComfyUI, so a
    healthy Ollama is *available for chat* even when ComfyUI is down (and the
    reverse). This is the fix for the "local health is ComfyUI-only" bug.
  * ComputeRouter is a behaviour-preserving seam: in local mode it delegates to
    llm.chat with identical arguments, and it only falls back off a *remote*
    provider (pre-output, non-streaming) to a healthy local runtime.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ---- modality-specific local health -------------------------------------

async def test_local_chat_health_uses_ollama_not_comfyui(monkeypatch):
    from app.compute import local as local_mod

    # Ollama up, ComfyUI down.
    monkeypatch.setattr(local_mod, "_comfy_healthy", lambda: False)
    async def _ollama_up():
        return True
    monkeypatch.setattr(local_mod, "_ollama_healthy", _ollama_up)

    provider = local_mod.LocalComputeProvider()
    assert await provider.available("chat") is True      # chat → Ollama (up)
    assert await provider.available("image") is False     # image → ComfyUI (down)


async def test_local_image_health_uses_comfyui_not_ollama(monkeypatch):
    from app.compute import local as local_mod

    # ComfyUI up, Ollama down.
    monkeypatch.setattr(local_mod, "_comfy_healthy", lambda: True)
    async def _ollama_down():
        return False
    monkeypatch.setattr(local_mod, "_ollama_healthy", _ollama_down)

    provider = local_mod.LocalComputeProvider()
    assert await provider.available("image") is True      # image → ComfyUI (up)
    assert await provider.available("chat") is False       # chat → Ollama (down)
    assert await provider.available(None) is True          # any runtime up


async def test_auto_mode_resolves_local_for_chat_when_only_ollama_up(monkeypatch):
    from app.compute import local as local_mod

    monkeypatch.setattr("app.config.HOMEPILOT_COMPUTE_MODE", "auto", raising=False)
    monkeypatch.setattr(local_mod, "_comfy_healthy", lambda: False)  # ComfyUI down
    async def _ollama_up():
        return True
    monkeypatch.setattr(local_mod, "_ollama_healthy", _ollama_up)    # Ollama up

    from app.compute import resolve_mode
    assert await resolve_mode("chat") == "local"


# ---- ComputeRouter seam -------------------------------------------------

async def test_route_chat_local_delegates_with_identical_args(compute_db, monkeypatch):
    monkeypatch.setattr("app.config.HOMEPILOT_COMPUTE_MODE", "local", raising=False)

    captured: dict = {}

    async def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr("app.llm.chat", fake_chat, raising=False)

    from app.compute import route_chat
    msgs = [{"role": "user", "content": "hi"}]
    out = await route_chat(
        msgs, provider="ollama", model="llama3.2:3b",
        base_url="http://x", temperature=0.3, max_tokens=150,
    )
    assert out["choices"][0]["message"]["content"] == "ok"
    assert captured["messages"] is msgs
    # Local delegation forwards exactly what llm.chat expects — nothing dropped.
    assert captured["kwargs"] == {
        "model": "llama3.2:3b", "provider": "ollama",
        "base_url": "http://x", "temperature": 0.3, "max_tokens": 150,
    }


class _FakeCloud:
    """Stands in for the Cloud relay; its chat always fails (unreachable)."""
    name = "ollabridge_cloud"
    async def chat(self, **_):
        raise ConnectionError("cloud unreachable")


async def test_router_falls_back_from_remote_to_local(compute_db, monkeypatch):
    from app.compute import registry
    from app.compute.router import ComputeRouter
    from app.compute.schemas import ModelRoute

    # Pin the model to the Cloud relay, with local as the explicit fallback.
    monkeypatch.setattr("app.compute.providers._build_cloud", lambda settings: _FakeCloud())
    registry.upsert_route(ModelRoute(
        modality="chat", model_id="m", primary_target="ollabridge_cloud",
        fallback_targets=["local"], strategy="pinned",
    ))

    async def fake_chat(messages, **kwargs):
        return {"choices": [{"message": {"content": "served-locally"}}]}
    monkeypatch.setattr("app.llm.chat", fake_chat, raising=False)

    out = await ComputeRouter().chat([{"role": "user", "content": "hi"}], model="m")
    # Cloud failed pre-output, so the request fell through to the local runtime.
    assert out["choices"][0]["message"]["content"] == "served-locally"


async def test_route_report_records_local_winner(compute_db, monkeypatch):
    monkeypatch.setattr("app.config.HOMEPILOT_COMPUTE_MODE", "local", raising=False)

    async def fake_chat(messages, **kwargs):
        return {"choices": [{"message": {"content": "ok"}}]}
    monkeypatch.setattr("app.llm.chat", fake_chat, raising=False)

    from app.compute import route_chat
    from app.compute.router import build_diagnostics
    report: dict = {}
    await route_chat([{"role": "user", "content": "hi"}], model="m", report=report)
    diag = build_diagnostics(report)
    assert diag["target"] == "local" and diag["label"] == "This PC"
    assert diag["fell_back"] is False


async def test_route_report_records_fallback_and_device_label(compute_db, monkeypatch):
    from app.compute import registry
    from app.compute.router import ComputeRouter, build_diagnostics, describe_target
    from app.compute.schemas import ModelRoute, ComputeDevice

    # Name the device so diagnostics can label it, and pin the model to it.
    registry.upsert_device(ComputeDevice(id="colab", source_id="ollabridge-cloud", name="Colab T4", online=True))
    registry.upsert_route(ModelRoute(
        modality="chat", model_id="m", primary_target="device:colab",
        fallback_targets=["local"], strategy="pinned",
    ))
    monkeypatch.setattr("app.compute.providers._build_cloud", lambda settings: _FakeCloud())

    async def fake_chat(messages, **kwargs):
        return {"choices": [{"message": {"content": "served-locally"}}]}
    monkeypatch.setattr("app.llm.chat", fake_chat, raising=False)

    assert describe_target("device:colab") == "Colab T4"

    report: dict = {}
    await ComputeRouter().chat([{"role": "user", "content": "hi"}], model="m", report=report)
    diag = build_diagnostics(report)
    # Cloud failed → fell back to local; the report explains why.
    assert diag["target"] == "local" and diag["fell_back"] is True
    assert diag["reason"]  # carries the cloud failure reason


async def test_offline_device_reason_names_heartbeat_age(compute_db, monkeypatch):
    import time as _t
    from app.compute import registry
    from app.compute.router import ComputeRouter, build_diagnostics
    from app.compute.schemas import ModelRoute, ComputeDevice

    # A device Cloud last reported offline 22s ago.
    registry.upsert_device(ComputeDevice(
        id="colab", source_id="ollabridge-cloud", name="Colab T4",
        online=False, last_heartbeat=_t.time() - 22,
    ))
    registry.upsert_route(ModelRoute(
        modality="chat", model_id="m", primary_target="device:colab",
        fallback_targets=["local"], strategy="pinned",
    ))

    async def fake_chat(messages, **kwargs):
        return {"choices": [{"message": {"content": "local"}}]}
    monkeypatch.setattr("app.llm.chat", fake_chat, raising=False)

    report: dict = {}
    await ComputeRouter().chat([{"role": "user", "content": "hi"}], model="m", report=report)
    diag = build_diagnostics(report)
    assert diag["target"] == "local" and diag["fell_back"] is True
    # The premium, actionable reason — device name + heartbeat age.
    assert "Colab T4 offline" in diag["reason"]
    assert "heartbeat expired" in diag["reason"]


async def test_router_reraises_when_all_targets_fail(compute_db, monkeypatch):
    from app.compute import registry
    from app.compute.router import ComputeRouter
    from app.compute.schemas import ModelRoute

    monkeypatch.setattr("app.compute.providers._build_cloud", lambda settings: _FakeCloud())
    registry.upsert_route(ModelRoute(
        modality="chat", model_id="m", primary_target="ollabridge_cloud",
        fallback_targets=[], strategy="pinned",
    ))

    async def failing_chat(messages, **kwargs):
        raise ConnectionError("local down too")
    monkeypatch.setattr("app.llm.chat", failing_chat, raising=False)

    # Cloud fails, and the safe local tail fails too → the error propagates.
    with pytest.raises(ConnectionError):
        await ComputeRouter().chat([{"role": "user", "content": "hi"}], model="m")
