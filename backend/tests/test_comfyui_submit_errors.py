"""A running ComfyUI that refuses a workflow is reported with its reason, not as "unavailable"."""
import asyncio

import httpx
import pytest

from app.services.comfyui import client as cc
from app.services.comfyui.errors import ComfyUIUnavailable, ComfyUIWorkflowError


def _patch_post(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(cc.httpx, "AsyncClient", factory)


def test_rejection_carries_comfyui_reason(monkeypatch):
    body = {
        "error": {"message": "Prompt outputs failed validation"},
        "node_errors": {"4": {"class_type": "CheckpointLoaderSimple",
                              "errors": [{"message": "Value not in list", "details": "ckpt_name: 'x.safetensors'"}]}},
    }
    _patch_post(monkeypatch, lambda req: httpx.Response(400, json=body))
    with pytest.raises(ComfyUIWorkflowError) as exc:
        asyncio.run(cc.submit_prompt("http://comfy", {"1": {}}))
    msg = str(exc.value)
    assert "failed validation" in msg and "CheckpointLoaderSimple #4" in msg and "x.safetensors" in msg


def test_unreachable_is_still_unavailable(monkeypatch):
    def boom(req):
        raise httpx.ConnectError("refused")
    _patch_post(monkeypatch, boom)
    with pytest.raises(ComfyUIUnavailable):
        asyncio.run(cc.submit_prompt("http://comfy", {"1": {}}))


def test_accepted_returns_prompt_id(monkeypatch):
    _patch_post(monkeypatch, lambda req: httpx.Response(200, json={"prompt_id": "abc"}))
    assert asyncio.run(cc.submit_prompt("http://comfy", {"1": {}})) == "abc"
