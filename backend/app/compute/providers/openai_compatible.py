"""
OpenAI-compatible compute provider (PR 2).

A ``direct`` source: HomePilot talks straight to any endpoint that speaks the
OpenAI ``/v1/chat/completions`` shape (a self-hosted vLLM, a hosted router, a
generic gateway). The base URL comes from the ``ComputeSource``; the API key
comes from the server-side secrets store via the source's ``credential_ref`` —
never from the client.

Transport is injectable so it is unit-testable without a live endpoint.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from ..base import ComputeProvider, iter_openai_sse


class OpenAICompatibleComputeProvider(ComputeProvider):
    name = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        *,
        default_model: Optional[str] = None,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.timeout = timeout
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout, transport=self._transport
        )

    async def generate_image(self, *, prompt, model=None, **extra) -> Any:
        raise NotImplementedError(f"{self.name} does not support image generation")

    async def chat(self, *, model, messages, **extra) -> dict:
        body: dict[str, Any] = {"model": model or self.default_model or "", "messages": messages}
        for key in ("temperature", "max_tokens"):
            if extra.get(key) is not None:
                body[key] = extra[key]
        async with self._client(self.timeout) as client:
            r = await client.post(
                "/v1/chat/completions", json=body, headers=self._headers()
            )
            r.raise_for_status()
            return r.json()

    async def chat_stream(self, *, model, messages, **extra):
        body: dict[str, Any] = {"model": model or self.default_model or "", "messages": messages, "stream": True}
        for key in ("temperature", "max_tokens"):
            if extra.get(key) is not None:
                body[key] = extra[key]
        async with self._client(self.timeout) as client:
            async with client.stream(
                "POST", "/v1/chat/completions", json=body, headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                async for delta in iter_openai_sse(resp):
                    yield delta

    async def available(self, modality: str | None = None) -> bool:
        if not self.base_url:
            return False
        # Only chat is supported; anything else is "unavailable" here.
        if modality not in (None, "chat", "multimodal"):
            return False
        try:
            async with self._client(5.0) as client:
                # /v1/models is the conventional liveness probe; tolerate 401
                # (endpoint is up, key may be scoped) as "reachable".
                r = await client.get("/v1/models", headers=self._headers())
                return r.status_code < 500
        except Exception:
            return False

    def describe(self) -> dict[str, Any]:
        return {
            "provider": "openai_compatible",
            "base_url": self.base_url,
            "configured": bool(self.api_key),
        }
