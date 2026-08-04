"""
Routing policies (PR 2).

Turns a ``(modality, model_id)`` request into an *ordered list of targets* to
try. Resolution order matches the design doc:

    1. Explicit per-model route (registry).
    2. Modality default (persisted settings).
    3. Global compute default (settings.compute_mode — the ex-env flag).
    4. Safe fallback policy (a local tail, unless privacy forbids it).

Targets are opaque strings the providers factory knows how to build:

    "local"                     local runtime (Ollama/ComfyUI)
    "ollabridge_cloud"          the Cloud relay, any owned device
    "ollabridge:any"            alias of the above
    "device:<id>"               the Cloud relay pinned to one device
    "source:<id>"               a configured ComputeSource (e.g. OpenAI-compatible)
    "provider:<alias>"          a hosted-provider alias (e.g. free-best)

This module is pure and synchronous: it does the *static* filtering (privacy,
manifest capability, VRAM) and ordering. Dynamic health/heartbeat filtering is
the router's job, because it owns the cached probes — the doc's "don't ping
every endpoint per request" rule.
"""

from __future__ import annotations

from typing import Optional

from . import registry
from .schemas import ComputeSettings, ModelRoute

# modality → the capability a device manifest must advertise to serve it.
_MODALITY_CAPABILITY = {
    "chat": "chat",
    "multimodal": "multimodal",
    "image": "image",
    "video": "video",
    "edit": "edit",
}

_HOSTED_PREFIXES = ("provider:",)
_REMOTE_PREFIXES = ("ollabridge", "device:", "source:", "provider:")


def _mode_targets(compute_mode: str, modality: str) -> list[str]:
    mode = (compute_mode or "local").strip().lower()
    if mode == "ollabridge_cloud":
        return ["ollabridge_cloud"]
    if mode == "auto":
        # prefer local, then burst to the Cloud relay (PR 1 `auto` semantics).
        return ["local", "ollabridge_cloud"]
    return ["local"]


def _order_by_strategy(strategy: str, primary: str, fallbacks: list[str]) -> list[str]:
    ordered = [primary, *fallbacks]
    if strategy == "prefer_local":
        ordered.sort(key=lambda t: 0 if t == "local" else 1)
    elif strategy == "prefer_remote":
        ordered.sort(key=lambda t: 0 if _is_remote(t) else 1)
    # "pinned" and "lowest_cost" keep the author's order (no cost model yet).
    return ordered


def _is_remote(target: str) -> bool:
    return any(target.startswith(p) or target == p.rstrip(":") for p in _REMOTE_PREFIXES)


def _is_hosted(target: str) -> bool:
    return any(target.startswith(p) for p in _HOSTED_PREFIXES)


def _dedupe(targets: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in targets:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _apply_privacy(targets: list[str], privacy: str) -> list[str]:
    if privacy == "local_only":
        return [t for t in targets if t == "local"]
    if privacy == "private_nodes":
        # own machines and private relays/devices/sources — but no hosted APIs.
        return [t for t in targets if not _is_hosted(t)]
    return targets  # hosted_allowed


def _capability_ok(model_id: str, target: str, modality: str) -> bool:
    """Static capability/VRAM filter for device-pinned targets, when we have a
    manifest to check against. No manifest ⇒ we don't block (optimistic)."""
    if not target.startswith("device:"):
        return True
    manifest = registry.get_manifest(model_id)
    if manifest is None:
        return True
    device_id = target.split(":", 1)[1]
    if manifest.device_ids and device_id not in manifest.device_ids:
        return False
    need = _MODALITY_CAPABILITY.get(modality)
    if need and manifest.capabilities and not manifest.supports(need):
        return False
    if manifest.minimum_vram_mb:
        device = registry.get_device(device_id)
        if device and device.vram_mb is not None and device.vram_mb < manifest.minimum_vram_mb:
            return False
    return True


def resolve_targets(
    modality: str,
    model_id: Optional[str] = None,
    *,
    settings: Optional[ComputeSettings] = None,
) -> list[str]:
    """Ordered targets to try for this request (see module docstring)."""
    settings = settings or registry.load_settings()

    route: Optional[ModelRoute] = (
        registry.get_route(model_id, modality) if model_id else None
    )
    if route is not None:
        targets = _order_by_strategy(
            route.normalized_strategy(), route.primary_target, list(route.fallback_targets)
        )
        privacy = route.normalized_privacy()
    else:
        default = settings.default_for(modality)
        if default is not None:
            primary = default.target or _mode_targets(settings.compute_mode, modality)[0]
            targets = _order_by_strategy(
                default.strategy, primary, list(default.fallback_targets)
            )
            privacy = default.privacy
        else:
            targets = _mode_targets(settings.compute_mode, modality)
            privacy = "private_nodes"

    # Static filters: privacy, then per-model capability/VRAM.
    targets = _apply_privacy(targets, privacy)
    if model_id:
        targets = [t for t in targets if _capability_ok(model_id, t, modality)]

    # Budget filter (PR 5): drop targets we *know* exceed the per-request budget.
    # Unknown-cost targets are kept (surfaced in explain, not silently dropped).
    from . import cost
    budget = cost.effective_budget_usd(route.max_cost_usd if route else None, settings)
    if budget is not None:
        targets = [
            t for t in targets
            if cost.within_budget(cost.estimate_target(t, modality, settings), budget)
        ]

    targets = _dedupe(targets)

    # Safe fallback tail: a local runtime is always the last resort unless the
    # privacy policy explicitly forbids leaving... it never does for local.
    if privacy != "local_only" and "local" not in targets:
        targets.append("local")
    if not targets:
        targets = ["local"]
    return targets


def explain(modality: str, model_id: Optional[str] = None) -> dict:
    """Diagnostics for the admin UI / request tracing — now cost-aware.

    Reports the chosen order, the per-request budget in force, and, for every
    *candidate* target (before the budget filter), its cost estimate and whether
    the budget excluded it — so the UI can say why a hosted option was skipped.
    """
    from . import cost
    route = registry.get_route(model_id, modality) if model_id else None
    settings = registry.load_settings()
    budget = cost.effective_budget_usd(route.max_cost_usd if route else None, settings)

    chosen = resolve_targets(modality, model_id, settings=settings)

    # Candidate set = chosen targets ∪ anything the budget removed, so the
    # explanation can show excluded hosted options with their price.
    candidates = list(chosen)
    if route is not None:
        for t in [route.primary_target, *route.fallback_targets]:
            if t not in candidates:
                candidates.append(t)

    costs = []
    for t in candidates:
        est = cost.estimate_target(t, modality, settings)
        over = budget is not None and est.known and not cost.within_budget(est, budget)
        row = est.to_dict()
        row["over_budget"] = over
        row["selected"] = t in chosen
        costs.append(row)

    return {
        "modality": modality,
        "model_id": model_id,
        "matched": (
            "route" if route is not None
            else "modality_default" if settings.default_for(modality) is not None
            else "global_default"
        ),
        "compute_mode": settings.compute_mode,
        "budget_usd": budget,
        "targets": chosen,
        "costs": costs,
    }
