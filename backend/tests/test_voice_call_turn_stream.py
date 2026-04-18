"""
Unit tests for ``voice_call.turn_stream``.

Anchored to ``docs/analysis/voice-call-streaming-design.md`` § 4.1
and § 4.2. Each test names the exact invariant it protects.

We don't stand up a real chat provider here — ``httpx.MockTransport``
lets us script HTTP responses (including SSE / NDJSON stream bodies)
and assert the generator behaves correctly on each shape.
"""
from __future__ import annotations

import asyncio
from typing import List

import httpx
import pytest

from app.voice_call import barge_in as bi
from app.voice_call import turn_stream as ts


@pytest.fixture(autouse=True)
def _clean_registry():
    bi._reset_for_tests()
    yield
    bi._reset_for_tests()


def _install_transport(monkeypatch, handler) -> None:
    """Patch ``httpx.AsyncClient`` so every call inside turn_stream
    uses our MockTransport. We wrap the real AsyncClient constructor
    to inject ``transport=``, leaving the rest of the call shape
    untouched."""
    original = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


async def _collect(agen) -> List[str]:
    out: List[str] = []
    async for d in agen:
        out.append(d)
    return out


# ── native streaming path (the Phase 2 happy path) ────────────────────

def test_native_streaming_yields_deltas_in_order(monkeypatch):
    """Three SSE chunks → three deltas in the exact order they
    arrived on the wire."""
    body = (
        b'data: {"choices":[{"delta":{"content":"hello "}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"there "}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"friend"}}]}\n\n'
        b'data: [DONE]\n\n'
    )

    def handler(req):
        assert req.url.path == "/v1/chat/completions"
        assert req.headers.get("content-type") == "application/json"
        return httpx.Response(200, content=body)

    _install_transport(monkeypatch, handler)
    token = bi.new_token("sid", "t1")

    async def _run():
        gen = ts.run_turn_streaming(
            user_text="hi", model="llama3:8b", cancel_token=token,
        )
        return await _collect(gen)

    deltas = asyncio.run(_run())
    assert deltas == ["hello ", "there ", "friend"]
    assert token.is_cancelled() is False


def test_native_streaming_respects_cancel(monkeypatch):
    """When the token is cancelled mid-stream, the generator must
    stop yielding AND exit cleanly (no exception)."""
    body = b""
    for i in range(10):
        body += f'data: {{"choices":[{{"delta":{{"content":"w{i} "}}}}]}}\n\n'.encode()
    body += b"data: [DONE]\n\n"

    def handler(req):
        return httpx.Response(200, content=body)

    _install_transport(monkeypatch, handler)
    token = bi.new_token("sid2", "t2")

    async def _run():
        out: List[str] = []
        async for d in ts.run_turn_streaming(
            user_text="hi", model="llama3:8b", cancel_token=token,
        ):
            out.append(d)
            if len(out) == 3:
                token.cancel()
        return out

    deltas = asyncio.run(_run())
    assert len(deltas) == 3, deltas
    assert token.is_cancelled() is True


def test_native_streaming_parses_ollama_ndjson(monkeypatch):
    """Same generator handles Ollama's message.content shape, not
    just OpenAI's choices[0].delta.content shape."""
    body = (
        b'{"message":{"content":"one "},"done":false}\n'
        b'{"message":{"content":"two"},"done":true}\n'
    )

    def handler(req):
        return httpx.Response(200, content=body)

    _install_transport(monkeypatch, handler)
    token = bi.new_token("sid3", "t3")

    async def _run():
        return await _collect(
            ts.run_turn_streaming(
                user_text="hi", model="llama3:8b", cancel_token=token,
            )
        )

    deltas = asyncio.run(_run())
    assert deltas == ["one ", "two"]


def test_native_streaming_raises_on_upstream_5xx(monkeypatch):
    """Non-2xx, non-501 HTTP errors must surface as RuntimeError so
    the WS handler can emit assistant.turn_end {reason: error}."""
    def handler(req):
        return httpx.Response(500, text="boom")

    _install_transport(monkeypatch, handler)
    token = bi.new_token("sid4", "t4")

    async def _run():
        async for _ in ts.run_turn_streaming(
            user_text="hi", model="llama3:8b", cancel_token=token,
        ):
            pass

    with pytest.raises(RuntimeError, match="500"):
        asyncio.run(_run())


# ── chunked-unary fallback (today's compat-endpoint behaviour) ────────

def test_fallback_on_501_emits_sentence_chunks(monkeypatch):
    """When the compat endpoint returns 501 on stream=true, we
    retry unary and emit the text in clause-sized chunks."""
    reply = "Hello there. How are you today? I'm doing well."

    def handler(req):
        body = req.content.decode("utf-8")
        if '"stream": true' in body or '"stream":true' in body:
            return httpx.Response(501, text="streaming not implemented")
        # Second (unary) request — return the full reply.
        return httpx.Response(200, json={
            "choices": [{"message": {"content": reply}}],
        })

    _install_transport(monkeypatch, handler)
    # Drop the per-chunk delay so the test runs in <1 ms.
    monkeypatch.setattr(ts, "_FALLBACK_INTER_CHUNK_MS", 0)
    token = bi.new_token("sid5", "t5")

    async def _run():
        return await _collect(
            ts.run_turn_streaming(
                user_text="hi", model="llama3:8b", cancel_token=token,
            )
        )

    deltas = asyncio.run(_run())
    # Three sentences → three chunks. Concatenation recovers the
    # original text up to a trailing space.
    assert len(deltas) == 3, deltas
    assert "".join(deltas).rstrip() == reply


def test_fallback_respects_cancel(monkeypatch):
    """Barge-in mid-fallback must stop emission just like the native
    path."""
    reply = ". ".join([f"Sentence {i}." for i in range(6)])

    def handler(req):
        body = req.content.decode("utf-8")
        if '"stream": true' in body or '"stream":true' in body:
            return httpx.Response(501)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": reply}}],
        })

    _install_transport(monkeypatch, handler)
    monkeypatch.setattr(ts, "_FALLBACK_INTER_CHUNK_MS", 0)
    token = bi.new_token("sid6", "t6")

    async def _run():
        out: List[str] = []
        async for d in ts.run_turn_streaming(
            user_text="hi", model="llama3:8b", cancel_token=token,
        ):
            out.append(d)
            if len(out) == 2:
                token.cancel()
        return out

    deltas = asyncio.run(_run())
    assert len(deltas) == 2, deltas


# ── suffix attachment (persona_call is orthogonal to streaming) ──────

def test_additional_system_is_prepended(monkeypatch):
    """The persona_call suffix must sit in the messages array at the
    position the non-streaming path already uses — immediately after
    system_prompt, before history + user text. Identical byte-for-byte
    to turn.run_turn's layout."""
    captured = {}

    def handler(req):
        captured["body"] = req.content.decode("utf-8")
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    _install_transport(monkeypatch, handler)
    token = bi.new_token("sid7", "t7")

    async def _run():
        async for _ in ts.run_turn_streaming(
            user_text="hi",
            model="llama3:8b",
            additional_system="[phone context: late night]",
            cancel_token=token,
        ):
            pass

    asyncio.run(_run())
    body = captured["body"]
    # The suffix must appear BEFORE the user message in the messages
    # array (system messages always precede user in the wire order).
    suffix_pos = body.find("[phone context: late night]")
    user_pos = body.find('"content": "hi"')
    if user_pos == -1:
        user_pos = body.find('"content":"hi"')
    assert suffix_pos != -1 and user_pos != -1, body
    assert suffix_pos < user_pos, (suffix_pos, user_pos)
