"""
HostedGatewayProvider — the ``provider:<alias>`` routing target.

Sends a chat request to OllaBridge Cloud's OpenAI-compatible endpoint under a
signed routing policy (``compute/routing.py``). OllaBridge picks the provider
— Hugging Face first, then other free APIs, then authorised paid APIs, then
the user's own paired devices — and reports which one answered. HomePilot does
not keep a second provider list or a second selection algorithm.

What this class adds on the HomePilot side:

* the per-request policy and (only this user's) forwarded credentials;
* provenance: who answered, on which tier, at what cost — recorded in the
  spending ledger and surfaced to the chat UI through ``answered_by``;
* structured errors (:class:`GatewayError`) instead of opaque HTTP failures.

The HTTP transport is injectable so the provider is testable without a gateway.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Optional

import httpx

from .. import routing
from ..base import ComputeProvider, GeneratedMedia

_KIND_LABEL = {
    "huggingface": "huggingface", "device": "my_computer",
}


class GatewayError(RuntimeError):
    """The gateway refused or could not serve the request."""

    def __init__(self, code: str, message: str, *, status: int = 0,
                 attempts: Optional[list] = None) -> None:
        self.code = code
        self.status = status
        self.attempts = attempts or []
        super().__init__(f"{code}: {message}" if code else message)


def _error_from(status: int, body: Any) -> GatewayError:
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        code = detail.get("error")
        if isinstance(code, dict):       # {"error": {"type": ..., "message": ...}}
            return GatewayError(str(code.get("type") or "gateway_error"),
                                str(code.get("message") or ""), status=status)
        return GatewayError(str(code or "gateway_error"), str(detail.get("message") or ""),
                            status=status, attempts=detail.get("attempts"))
    text = detail if isinstance(detail, str) else json.dumps(body)[:200] if body else ""
    code = {401: "auth_failed", 403: "auth_failed", 404: "model_not_found",
            429: "rate_limited"}.get(status, "provider_unavailable")
    return GatewayError(code, str(text), status=status)


def _header_provenance(headers: Any) -> Optional[dict]:
    raw = headers.get("x-ollabridge-provenance") if headers is not None else None
    if not raw:
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except Exception:
        return None


def answered_by(provenance: dict) -> dict:
    """Provenance in the shape the chat UI already renders under a message."""
    kind = str(provenance.get("provider_kind") or provenance.get("provider") or "")
    if kind in ("openai_compatible", ""):
        kind = str(provenance.get("provider") or kind)   # the generic adapter says nothing
    reason = provenance.get("fallback_reason")
    return {
        "provider": _KIND_LABEL.get(kind, kind),
        "model": provenance.get("model") or "",
        "fell_back": bool(provenance.get("fell_back")),
        "reason": _REASONS.get(reason, reason) if reason else None,
        "via": "ollabridge",
        "tier": provenance.get("tier"),
        "billing": provenance.get("billing"),
        "execution": provenance.get("execution"),
        "credential": provenance.get("credential"),
        "cost": provenance.get("cost"),
        "request_id": provenance.get("request_id"),
    }


_REASONS = {
    "quota_exhausted": "Hugging Face credits ran out",
    "rate_limited": "the first provider is rate limiting this account",
    "auth_failed": "the first provider did not accept the token",
    "missing_credentials": "the first provider has no credential configured",
    "provider_timeout": "the first provider timed out",
    "provider_unavailable": "the first provider did not answer",
    "model_not_found": "the chosen model is not served right now",
    "unsupported_capability": "the first model cannot do this kind of request",
    "paid_not_authorized": "paid inference is not authorised",
    "budget_exceeded": "the spending limit would be exceeded",
}


class HostedGatewayProvider(ComputeProvider):
    name = "hosted_gateway"
    #: Test seam: transport used when none is passed to the constructor.
    default_transport: httpx.BaseTransport | None = None

    def __init__(
        self,
        base_url: str,
        alias: str,
        *,
        user_id: str,
        vision_alias: Optional[str] = None,
        timeout: float = 300.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.alias = alias
        self.vision_alias = vision_alias or alias
        self.user_id = user_id
        self.timeout = timeout
        self._transport = transport or type(self).default_transport

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=timeout,
                                 transport=self._transport)

    @staticmethod
    def _has_image(messages: list[dict]) -> bool:
        for m in messages or []:
            content = m.get("content") if isinstance(m, dict) else None
            if isinstance(content, list) and any(
                isinstance(p, dict) and p.get("type") in ("image_url", "input_image")
                for p in content
            ):
                return True
        return False

    def _prepare(self, model: Optional[str], messages: list[dict], modality: str):
        vision = modality == "multimodal" or self._has_image(messages)
        prefer = None
        # A Hub repo id the user picked in Models is a preference inside the
        # Hugging Face tier — the fallback chain still applies after it.
        if model and "/" in model and not model.startswith(("persona:", "personality:")):
            prefer = model[3:] if model.startswith("hf:") else model
        call = routing.build_gateway_call(
            self.user_id,
            modality="multimodal" if vision else "chat",
            require=("vision",) if vision else (),
            prefer_model=prefer,
        )
        if not call.token:
            raise GatewayError("missing_credentials",
                               "OllaBridge Cloud is not linked for this account.")
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {call.token}", **call.headers}
        alias = self.vision_alias if vision else self.alias
        return alias, headers, call, ("multimodal" if vision else "chat")

    def _served(self, provenance: Optional[dict], modality: str) -> None:
        if not provenance:
            return
        routing.note_provenance(provenance)
        routing.record_usage(self.user_id, provenance, modality=modality)

    # ---- ComputeProvider ----

    async def chat(self, *, model, messages, modality: str = "chat", **extra) -> dict:
        alias, headers, _call, kind = self._prepare(model, messages, modality)
        body: dict[str, Any] = {"model": alias, "messages": messages}
        body.update({k: v for k, v in extra.items()
                     if v is not None and k not in ("provider", "base_url", "routing")})
        async with self._client(self.timeout) as client:
            r = await client.post("/v1/chat/completions", json=body, headers=headers)
        try:
            data = r.json()
        except Exception:
            data = {}
        if r.status_code != 200:
            raise _error_from(r.status_code, data)
        provenance = data.get("ollabridge") or _header_provenance(r.headers)
        if provenance:
            self._served(provenance, kind)
            data["answered_by"] = answered_by(provenance)
            data.setdefault("model", provenance.get("model"))
        return data

    async def chat_stream(self, *, model, messages, modality: str = "chat", **extra):
        alias, headers, _call, kind = self._prepare(model, messages, modality)
        body: dict[str, Any] = {"model": alias, "messages": messages, "stream": True}
        body.update({k: v for k, v in extra.items()
                     if v is not None and k not in ("provider", "base_url", "routing")})
        async with self._client(self.timeout) as client:
            async with client.stream("POST", "/v1/chat/completions",
                                     json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    raw = await resp.aread()
                    try:
                        data = json.loads(raw)
                    except Exception:
                        data = {}
                    raise _error_from(resp.status_code, data)
                provenance = _header_provenance(resp.headers)
                routing.note_provenance(provenance)
                try:
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if line.startswith(": ollabridge "):
                            # Final provenance (with the real token usage and
                            # cost) arrives as an SSE comment after the text.
                            try:
                                provenance = json.loads(line[len(": ollabridge "):])
                            except Exception:
                                pass
                            continue
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except Exception:
                            continue
                        if isinstance(obj, dict) and obj.get("error"):
                            err = obj["error"] if isinstance(obj["error"], dict) else {}
                            raise GatewayError(str(err.get("code") or "stream_interrupted"),
                                               str(err.get("message") or "stream interrupted"))
                        choices = obj.get("choices") or []
                        delta = (choices[0].get("delta") or {}).get("content") if choices else None
                        if delta:
                            yield delta
                finally:
                    self._served(provenance, kind)

    async def generate_image(self, **kwargs) -> GeneratedMedia:  # pragma: no cover
        raise GatewayError("unsupported_capability",
                           "provider:<alias> targets serve chat; media uses the jobs API.")

    edit_image = generate_image
    generate_video = generate_image

    async def available(self, modality: str | None = None) -> bool:
        if not self.base_url:
            return False
        try:
            async with self._client(5.0) as client:
                r = await client.get("/health")
                return r.status_code < 500
        except Exception:
            return False

    def describe(self) -> dict[str, Any]:
        return {"provider": "hosted_gateway", "cloud_url": self.base_url, "alias": self.alias}
