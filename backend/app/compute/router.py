"""
ComputeRouter (PR 1 seam, PR 2 per-model routing).

The single seam every inference path goes through. PR 1 made it a
behaviour-preserving façade over the global compute mode; PR 2 makes it resolve
a *per-model* plan from the registry and try candidates in order.

Resolution (see ``policies``):
    explicit route → modality default → global compute mode → safe local tail.

Dispatch:
    * Candidates are tried in order. The **real call is the health probe** — we
      don't ping every endpoint first (the design's rule). A cheap circuit
      breaker (``health.HealthCache.allows``) skips targets whose last attempt
      just failed, so a dead remote is retried at most once per TTL.
    * Fallback is **pre-output only**. These calls are non-streaming (they
      return a complete result), so a candidate failing means nothing reached
      the user and advancing to the next candidate is safe.
    * A local runtime is always the final safety net.

Behaviour preservation: with an empty registry, ``resolve_targets`` returns the
targets implied by ``settings.compute_mode`` (which defaults to the env flag),
so an unconfigured install routes exactly as PR 1 did.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from . import health, policies, providers
from .base import GeneratedMedia
from .local import LocalComputeProvider

# call(provider, extra) -> awaitable result
_Call = Callable[[Any, dict], Awaitable[Any]]


class ComputeRouter:
    def __init__(self, cache: Optional[health.HealthCache] = None):
        self._cache = cache or health.shared_cache()

    async def _dispatch(
        self,
        modality: str,
        model_id: Optional[str],
        call: _Call,
        report: Optional[dict] = None,
    ):
        targets = policies.resolve_targets(modality, model_id)
        settings = None
        last_exc: Optional[Exception] = None
        tried_local = False
        failures: list[dict] = []  # attempts that failed before a winner

        def _win(target: str, device_id: Optional[str]) -> None:
            if report is None:
                return
            report["target"] = target
            report["device_id"] = device_id
            report["fell_back"] = bool(failures)
            report["attempts"] = failures + [{"target": target, "ok": True}]
            if failures:
                report["reason"] = failures[0].get("reason")

        for target in targets:
            # Heartbeat-aware: don't dial a device the registry knows is offline —
            # skip it with an actionable reason instead of a doomed round-trip.
            offline = _device_offline_reason(target)
            if offline is not None:
                failures.append({"target": target, "ok": False, "reason": offline})
                continue
            built = providers.build_target(target, settings=settings)
            if built is None:
                failures.append({"target": target, "ok": False, "reason": "not available"})
                continue
            if not self._cache.allows(built.health_key):
                failures.append({"target": target, "ok": False, "reason": "recently failed"})
                continue
            if built.health_key == "local":
                tried_local = True
            try:
                result = await call(built.provider, built.extra)
                self._cache.record(built.health_key, True)
                _win(built.target, (built.extra.get("routing") or {}).get("device_id"))
                return self._annotate(result, built)
            except Exception as exc:  # pre-output: safe to advance
                last_exc = exc
                self._cache.record(built.health_key, False)
                failures.append({"target": target, "ok": False, "reason": str(exc)[:140]})
                continue

        # Final safety net: a local runtime, even if the breaker skipped it above.
        if not tried_local:
            local = LocalComputeProvider()
            try:
                result = await call(local, {})
                _win("local", None)
                return result
            except Exception as exc:
                last_exc = exc

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("no compute target available for this request")

    @staticmethod
    def _annotate(result: Any, built: providers.BuiltTarget) -> Any:
        # Surface which target served the request for diagnostics, without
        # changing the shape callers already consume.
        if isinstance(result, GeneratedMedia):
            result.meta.setdefault("target", built.target)
        return result

    # ---- public API ----

    async def chat(
        self,
        messages: list[dict],
        *,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        modality: str = "chat",
        base_url: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        report: Optional[dict] = None,
        **extra: Any,
    ) -> dict:
        async def call(p: Any, textra: dict) -> dict:
            if isinstance(p, LocalComputeProvider):
                return await p.chat(
                    model=model, messages=messages, provider=provider,
                    base_url=base_url, temperature=temperature,
                    max_tokens=max_tokens, **extra,
                )
            kwargs = {
                k: v for k, v in (
                    ("temperature", temperature), ("max_tokens", max_tokens),
                    *extra.items(), *textra.items(),
                ) if v is not None
            }
            return await p.chat(model=model or "", messages=messages, **kwargs)

        return await self._dispatch(modality, model, call, report=report)

    async def _dispatch_stream(self, modality, model_id, make_stream, report=None):
        """Streaming dispatch. Fallback happens **only before the first token** —
        once any delta has reached the caller we never restart on another target
        (the design's safe-streaming rule); a mid-stream failure is raised."""
        targets = policies.resolve_targets(modality, model_id)
        failures: list[dict] = []
        tried_local = False
        last_exc: Optional[Exception] = None

        def _win(target: str, device_id: Optional[str]) -> None:
            if report is None:
                return
            report["target"] = target
            report["device_id"] = device_id
            report["fell_back"] = bool(failures)
            report["attempts"] = failures + [{"target": target, "ok": True}]
            if failures:
                report["reason"] = failures[0].get("reason")

        async def _try(provider, extra, target, health_key):
            first = True
            async for delta in make_stream(provider, extra):
                if first:
                    self._cache.record(health_key, True)
                    _win(target, (extra.get("routing") or {}).get("device_id"))
                    first = False
                yield delta
            if first:  # completed with zero tokens — still a success
                self._cache.record(health_key, True)
                _win(target, (extra.get("routing") or {}).get("device_id"))

        for target in targets:
            offline = _device_offline_reason(target)
            if offline is not None:
                failures.append({"target": target, "ok": False, "reason": offline})
                continue
            built = providers.build_target(target)
            if built is None:
                failures.append({"target": target, "ok": False, "reason": "not available"})
                continue
            if not self._cache.allows(built.health_key):
                failures.append({"target": target, "ok": False, "reason": "recently failed"})
                continue
            if built.health_key == "local":
                tried_local = True
            emitted = False
            try:
                async for delta in _try(built.provider, built.extra, built.target, built.health_key):
                    emitted = True
                    yield delta
                return
            except Exception as exc:
                if emitted:
                    self._cache.record(built.health_key, False)
                    raise  # mid-stream — never restart
                last_exc = exc
                self._cache.record(built.health_key, False)
                failures.append({"target": target, "ok": False, "reason": str(exc)[:140]})
                continue

        if not tried_local:
            local = LocalComputeProvider()
            emitted = False
            try:
                async for delta in _try(local, {}, "local", "local"):
                    emitted = True
                    yield delta
                return
            except Exception as exc:
                if emitted:
                    raise
                last_exc = exc

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("no compute target available for this request")

    async def chat_stream(
        self,
        messages: list[dict],
        *,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        modality: str = "chat",
        base_url: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        report: Optional[dict] = None,
        **extra: Any,
    ):
        def make_stream(p: Any, textra: dict):
            if isinstance(p, LocalComputeProvider):
                return p.chat_stream(
                    model=model, messages=messages, provider=provider,
                    base_url=base_url, temperature=temperature,
                    max_tokens=max_tokens, **extra,
                )
            kwargs = {
                k: v for k, v in (
                    ("temperature", temperature), ("max_tokens", max_tokens),
                    *extra.items(), *textra.items(),
                ) if v is not None
            }
            return p.chat_stream(model=model or "", messages=messages, **kwargs)

        async for delta in self._dispatch_stream(modality, model, make_stream, report=report):
            yield delta

    async def generate_image(
        self, *, model: Optional[str] = None, modality: str = "image", **kwargs: Any
    ) -> GeneratedMedia:
        async def call(p: Any, textra: dict) -> GeneratedMedia:
            return await p.generate_image(model=model, **{**kwargs, **textra})
        return await self._dispatch(modality, model, call)

    async def edit_image(
        self, *, model: Optional[str] = None, modality: str = "edit", **kwargs: Any
    ) -> GeneratedMedia:
        async def call(p: Any, textra: dict) -> GeneratedMedia:
            return await p.edit_image(model=model, **{**kwargs, **textra})
        return await self._dispatch(modality, model, call)

    async def generate_video(
        self, *, model: Optional[str] = None, modality: str = "video", **kwargs: Any
    ) -> GeneratedMedia:
        async def call(p: Any, textra: dict) -> GeneratedMedia:
            return await p.generate_video(model=model, **{**kwargs, **textra})
        return await self._dispatch(modality, model, call)


async def route_chat(
    messages: list[dict],
    *,
    provider: str = "openai_compat",
    temperature: float = 0.7,
    max_tokens: int = 800,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    modality: str = "chat",
    report: Optional[dict] = None,
) -> dict:
    """Drop-in replacement for ``app.llm.chat`` that routes through the active
    compute plan. Signature mirrors ``llm.chat`` exactly; in the default
    (unconfigured / local) case this is the same call as before.

    Pass a mutable ``report`` dict to receive routing diagnostics (which target
    served the request, whether it fell back, and why) — see ``describe_target``.
    """
    return await ComputeRouter().chat(
        messages,
        model=model,
        provider=provider,
        modality=modality,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        report=report,
    )


def _device_offline_reason(target: str) -> Optional[str]:
    """If ``target`` is a device the registry reports offline, return an
    actionable reason ("Colab T4 offline — heartbeat expired 22s ago"); else
    None. Gated on the Cloud-authoritative ``online`` flag so an infrequent sync
    can't false-negative a device that's actually up — a live device that
    momentarily fails is handled by the normal exception path instead."""
    if not target.startswith("device:"):
        return None
    from . import registry
    did = target.split(":", 1)[1]
    dev = registry.get_device(did)
    if dev is None or dev.online:
        return None
    name = dev.name or did
    age = dev.heartbeat_age_s()
    if age is None:
        return f"{name} offline"
    return f"{name} offline — heartbeat expired {int(age)}s ago"


async def route_chat_stream(
    messages: list[dict],
    *,
    provider: str = "openai_compat",
    temperature: float = 0.7,
    max_tokens: int = 800,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    modality: str = "chat",
    report: Optional[dict] = None,
):
    """Streaming counterpart of ``route_chat`` — yields assistant text deltas
    through the active compute plan, with pre-first-token fallback."""
    async for delta in ComputeRouter().chat_stream(
        messages, model=model, provider=provider, modality=modality,
        base_url=base_url, temperature=temperature, max_tokens=max_tokens,
        report=report,
    ):
        yield delta


def describe_target(target: Optional[str], device_id: Optional[str] = None) -> str:
    """Human label for a routing target — 'This PC', 'Colab T4', 'OllaBridge
    Cloud', a source name — resolved against the registry."""
    if not target or target == "local":
        return "This PC"
    if target.startswith("ollabridge"):
        return "OllaBridge Cloud"
    from . import registry
    if target.startswith("device:"):
        did = target.split(":", 1)[1]
        dev = registry.get_device(did)
        return dev.name if dev and dev.name else f"Device {did}"
    if target.startswith("source:"):
        sid = target.split(":", 1)[1]
        src = registry.get_source(sid)
        return src.name if src and src.name else f"Source {sid}"
    if target.startswith("provider:"):
        return f"Provider {target.split(':', 1)[1]}"
    return target


def build_diagnostics(report: dict) -> Optional[dict]:
    """Shape a route ``report`` into the ``compute`` block the chat API returns
    (None when nothing was recorded)."""
    target = report.get("target")
    if not target:
        return None
    return {
        "target": target,
        "device_id": report.get("device_id"),
        "label": describe_target(target, report.get("device_id")),
        "fell_back": bool(report.get("fell_back")),
        "reason": report.get("reason"),
    }
