"""P1 — token streaming: provider/router streaming + safe-streaming fallback."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


async def _collect(agen):
    out = []
    async for x in agen:
        out.append(x)
    return out


# ---- OpenAI SSE parser ----------------------------------------------------

async def test_iter_openai_sse_parses_deltas():
    from app.compute.base import iter_openai_sse

    class FakeResp:
        async def aiter_lines(self):
            for l in [
                'data: {"choices":[{"delta":{"content":"Hel"}}]}',
                "",  # keep-alive blank
                'data: {"choices":[{"delta":{"content":"lo"}}]}',
                "data: [DONE]",
                'data: {"choices":[{"delta":{"content":"ignored"}}]}',
            ]:
                yield l

    assert await _collect(iter_openai_sse(FakeResp())) == ["Hel", "lo"]


# ---- local streaming via llm.stream_chat ----------------------------------

async def test_route_chat_stream_local(compute_db, monkeypatch):
    monkeypatch.setattr("app.config.HOMEPILOT_COMPUTE_MODE", "local", raising=False)

    async def fake_stream(messages, **kwargs):
        for tok in ["Hello", ", ", "world"]:
            yield tok
    monkeypatch.setattr("app.llm.stream_chat", fake_stream, raising=False)

    from app.compute.router import route_chat_stream, build_diagnostics
    report: dict = {}
    deltas = await _collect(route_chat_stream(
        [{"role": "user", "content": "hi"}], model="m", report=report))
    assert "".join(deltas) == "Hello, world"
    assert build_diagnostics(report)["target"] == "local"


# ---- safe-streaming fallback (before first token only) --------------------

class _CloudFailsBeforeToken:
    name = "ollabridge_cloud"
    async def chat_stream(self, **_):
        raise ConnectionError("cloud unreachable")
        yield  # pragma: no cover — makes this an async generator


class _CloudFailsMidStream:
    name = "ollabridge_cloud"
    async def chat_stream(self, **_):
        yield "partial "
        raise ConnectionError("dropped mid-stream")


def _pin_cloud(monkeypatch, cloud_obj):
    from app.compute import registry
    from app.compute.schemas import ModelRoute
    monkeypatch.setattr("app.compute.providers._build_cloud", lambda settings: cloud_obj)
    registry.upsert_route(ModelRoute(
        modality="chat", model_id="m", primary_target="ollabridge_cloud",
        fallback_targets=["local"], strategy="pinned"))


async def test_stream_falls_back_before_first_token(compute_db, monkeypatch):
    _pin_cloud(monkeypatch, _CloudFailsBeforeToken())

    async def fake_stream(messages, **kwargs):
        yield "served locally"
    monkeypatch.setattr("app.llm.stream_chat", fake_stream, raising=False)

    from app.compute.router import ComputeRouter, build_diagnostics
    report: dict = {}
    deltas = await _collect(ComputeRouter().chat_stream(
        [{"role": "user", "content": "hi"}], model="m", report=report))
    assert "".join(deltas) == "served locally"
    diag = build_diagnostics(report)
    assert diag["target"] == "local" and diag["fell_back"] is True and diag["reason"]


async def test_stream_never_restarts_after_first_token(compute_db, monkeypatch):
    _pin_cloud(monkeypatch, _CloudFailsMidStream())

    async def fake_stream(messages, **kwargs):
        yield "SHOULD-NOT-APPEAR"
    monkeypatch.setattr("app.llm.stream_chat", fake_stream, raising=False)

    from app.compute.router import ComputeRouter
    got = []
    with pytest.raises(ConnectionError):
        async for d in ComputeRouter().chat_stream(
            [{"role": "user", "content": "hi"}], model="m"):
            got.append(d)
    # The partial cloud token reached the caller; we did NOT restart on local.
    assert got == ["partial "]
