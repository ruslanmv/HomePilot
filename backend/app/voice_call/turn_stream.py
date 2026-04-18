"""
Streaming turn runner — async-generator peer of :func:`turn.run_turn`.

Yields assistant text chunks from the chat provider as they arrive so
the WebSocket handler can emit ``assistant.partial`` envelopes without
waiting for the full reply. Drops cleanly on barge-in cancel.

Contract is documented in
``docs/analysis/voice-call-streaming-design.md`` § 4.1 and § 4.2.

Two execution paths, selected at runtime:

  1. **Native streaming** — POST to the compat chat endpoint with
     ``stream: true`` and consume the SSE / NDJSON response. This is
     the real Phase 2 path and delivers sub-500 ms first-audio when
     the provider supports it.

  2. **Chunked-unary fallback** — if the compat endpoint returns 501
     (current default, see ``turn.py`` comment) OR the provider
     doesn't support streaming, we call the unary endpoint, receive
     the full reply, and emit it in clause-sized chunks with a tiny
     delay so the downstream plumbing (``assistant.partial`` →
     ``streamTts.appendDelta``) still exercises correctly.

The fallback yields no latency improvement — its value is keeping
the envelope contract and the client-side streaming TTS alive even
while the compat endpoint hasn't flipped on streaming. When it does,
this module starts getting real deltas automatically.

The persona_call suffix, persona resolution, and auth are all handled
by ``ws.py`` / the compat endpoint exactly as today. This module
receives the already-resolved ``user_text`` + ``model`` + headers
and does nothing with the persona layer directly.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import AsyncIterator, Dict, List, Optional

import httpx

from .barge_in import BargeInToken


def _local_backend_url() -> str:
    return (
        os.getenv("VOICE_CALL_INTERNAL_BACKEND_URL")
        or os.getenv("HOMEPILOT_INTERNAL_BACKEND_URL")
        or "http://127.0.0.1:8000"
    ).rstrip("/")


DEFAULT_TIMEOUT_SEC = float(os.getenv("VOICE_CALL_TURN_TIMEOUT_SEC", "60"))
# Chunk pacing for the fallback path. Kept deliberately small so the
# fallback "feels like" streaming without flooding the client.
_FALLBACK_INTER_CHUNK_MS = int(os.getenv("VOICE_CALL_FALLBACK_CHUNK_MS", "35"))

# Simple clause splitter used only by the fallback path. Deliberately
# naive: split on sentence-enders first, then on commas if a sentence
# is too long for one chunk.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_CHUNK_MAX_CHARS = 90


def _split_for_chunking(text: str) -> List[str]:
    if not text:
        return []
    parts = [p for p in _SENTENCE_SPLIT.split(text) if p]
    out: List[str] = []
    for part in parts:
        if len(part) <= _CHUNK_MAX_CHARS:
            out.append(part)
            continue
        # Long sentence — split on commas, rejoining short pieces so
        # we don't over-chunk.
        comma_bits = [b.strip() for b in part.split(",") if b.strip()]
        buf = ""
        for bit in comma_bits:
            if len(buf) + len(bit) + 2 <= _CHUNK_MAX_CHARS:
                buf = f"{buf}, {bit}" if buf else bit
            else:
                if buf:
                    out.append(buf)
                buf = bit
        if buf:
            out.append(buf)
    # Re-attach trailing whitespace so concatenation preserves spacing.
    return [f"{p} " if not p.endswith(" ") else p for p in out]


def _extract_delta_from_sse_line(line: str) -> Optional[str]:
    """Parse one SSE / NDJSON frame from a streaming chat endpoint.

    Supports both the OpenAI-style ``data: {...}`` SSE format and
    Ollama's raw NDJSON (``{"message": {...}}`` per line).
    """
    line = line.strip()
    if not line:
        return None
    if line.startswith("data:"):
        line = line[5:].strip()
    if line == "[DONE]":
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    # OpenAI streaming: choices[0].delta.content
    try:
        choices = obj.get("choices") or []
        if choices:
            delta = (choices[0] or {}).get("delta") or {}
            content = delta.get("content")
            if isinstance(content, str) and content:
                return content
    except (AttributeError, TypeError):
        pass
    # Ollama streaming: message.content
    try:
        msg = obj.get("message") or {}
        content = msg.get("content")
        if isinstance(content, str) and content:
            return content
    except (AttributeError, TypeError):
        pass
    return None


async def _yield_native_stream(
    client: httpx.AsyncClient,
    url: str,
    payload: Dict,
    headers: Dict[str, str],
    cancel_token: BargeInToken,
) -> AsyncIterator[str]:
    """Native provider streaming path — returns an async iterator of
    deltas. Caller handles 501 / 4xx / 5xx by catching the upstream
    status before entering this coroutine."""
    async with client.stream("POST", url, json=payload, headers=headers) as r:
        if r.status_code == 501:
            # Sentinel for "provider doesn't support streaming yet".
            # Caller will fall back to chunked-unary.
            await r.aread()
            raise _StreamingUnsupported()
        if r.status_code >= 400:
            body = (await r.aread()).decode("utf-8", errors="replace")
            raise RuntimeError(
                f"chat stream {url} returned {r.status_code}: {body[:400]}"
            )
        async for line in r.aiter_lines():
            if cancel_token.is_cancelled():
                return
            delta = _extract_delta_from_sse_line(line)
            if delta:
                yield delta


class _StreamingUnsupported(Exception):
    """Raised when the provider returns 501 on ``stream: true`` so the
    caller can route to the chunked-unary fallback without conflating
    it with an ordinary upstream error."""


async def _yield_chunked_unary(
    client: httpx.AsyncClient,
    url: str,
    payload: Dict,
    headers: Dict[str, str],
    cancel_token: BargeInToken,
) -> AsyncIterator[str]:
    """Fallback path — full unary call, then chunk the reply."""
    unary_payload = dict(payload, stream=False)
    r = await client.post(url, json=unary_payload, headers=headers)
    if r.status_code >= 400:
        raise RuntimeError(
            f"chat endpoint {url} returned {r.status_code}: {r.text[:400]}"
        )
    data = r.json()
    try:
        reply = (
            data["choices"][0]["message"]["content"]
            if data.get("choices")
            else ""
        )
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(
            f"chat endpoint returned an unexpected body shape: {str(data)[:400]}"
        )
    for chunk in _split_for_chunking(reply):
        if cancel_token.is_cancelled():
            return
        yield chunk
        # Small delay so the client's streaming TTS has a beat to
        # synth + play before the next chunk arrives. Keeps the
        # fallback from flooding the WS.
        await asyncio.sleep(_FALLBACK_INTER_CHUNK_MS / 1000.0)


async def run_turn_streaming(
    *,
    user_text: str,
    model: str,
    auth_bearer: Optional[str] = None,
    system_prompt: Optional[str] = None,
    additional_system: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
    extra_headers: Optional[Dict[str, str]] = None,
    cancel_token: BargeInToken,
) -> AsyncIterator[str]:
    """Yield assistant text chunks for the given user turn.

    Exits cleanly (no exception) when ``cancel_token`` is tripped by
    a barge-in. The caller is responsible for emitting the final
    ``assistant.turn_end`` envelope regardless of exit reason.
    """
    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if additional_system:
        messages.append({"role": "system", "content": additional_system})
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if auth_bearer:
        headers["Authorization"] = f"Bearer {auth_bearer}"
    if extra_headers:
        headers.update(extra_headers)

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "max_tokens": int(os.getenv("VOICE_CALL_TURN_MAX_TOKENS", "300")),
        "temperature": float(os.getenv("VOICE_CALL_TURN_TEMPERATURE", "0.7")),
    }

    url = f"{_local_backend_url()}/v1/chat/completions"

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SEC) as client:
        # Try native streaming first.
        try:
            async for delta in _yield_native_stream(
                client, url, payload, headers, cancel_token,
            ):
                yield delta
            return
        except _StreamingUnsupported:
            # Compat endpoint currently returns 501 on stream=true;
            # fall back to unary + chunker. Covered by test.
            pass
        async for delta in _yield_chunked_unary(
            client, url, payload, headers, cancel_token,
        ):
            yield delta
