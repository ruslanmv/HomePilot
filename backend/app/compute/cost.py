"""
Cost estimates for routing targets (PR 5).

Provider prices are **not hardcoded** (the design is explicit). Instead this
module reads a timestamped, user/operator-supplied catalog from persisted
settings (``ComputeSettings.cost_catalog``) — which can be synced from
OllaBridge's provider registry rather than duplicated here — and layers sensible
defaults on top:

  * ``local`` and your own private nodes (``device:``/``source:``/the Cloud
    relay) are **free** — no incremental GPU fee.
  * hosted-provider *free* aliases (``provider:free-*``) are free.
  * any other hosted target is **unknown** until the catalog gives a price
    (unknown never silently blocks a route; it's surfaced in explanations).

A catalog entry (keyed by exact target or by scheme, e.g. ``"provider:groq"`` or
``"source:"``) looks like::

    {"usd": 0.02, "per_unit": "request", "currency": "USD",
     "as_of": "2026-08-01", "note": "list price"}
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from .schemas import ComputeSettings


@dataclass
class CostEstimate:
    target: str
    currency: str = "USD"
    estimated_usd: Optional[float] = None   # None == unknown
    per_unit: str = "request"
    as_of: Optional[str] = None
    note: Optional[str] = None

    @property
    def known(self) -> bool:
        return self.estimated_usd is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "currency": self.currency,
            "estimated_usd": self.estimated_usd,
            "per_unit": self.per_unit,
            "as_of": self.as_of,
            "note": self.note,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _scheme(target: str) -> str:
    """The catalog bucket a target falls in when there's no exact match."""
    if target == "local":
        return "local"
    if target in ("ollabridge_cloud", "ollabridge:any"):
        return "ollabridge_cloud"
    for pref in ("device:", "source:", "provider:"):
        if target.startswith(pref):
            return pref
    return target


def _catalog_lookup(catalog: dict, target: str) -> Optional[dict]:
    if target in catalog:
        return catalog[target]
    scheme = _scheme(target)
    if scheme in catalog:
        return catalog[scheme]
    return None


def estimate_target(
    target: str, modality: str, settings: Optional[ComputeSettings] = None
) -> CostEstimate:
    """Best available cost estimate for running ``modality`` on ``target``."""
    from . import registry
    settings = settings or registry.load_settings()
    catalog = settings.cost_catalog or {}

    entry = _catalog_lookup(catalog, target)
    if entry is not None:
        return CostEstimate(
            target=target,
            currency=entry.get("currency", "USD"),
            estimated_usd=entry.get("usd"),
            per_unit=entry.get("per_unit", "request"),
            as_of=entry.get("as_of") or _now_iso(),
            note=entry.get("note"),
        )

    # Defaults when the catalog is silent.
    scheme = _scheme(target)
    if scheme in ("local", "ollabridge_cloud", "device:", "source:"):
        return CostEstimate(
            target=target, estimated_usd=0.0, as_of=_now_iso(),
            note="Your own hardware — no incremental fee",
        )
    if scheme == "provider:" and target.startswith("provider:free"):
        return CostEstimate(
            target=target, estimated_usd=0.0, as_of=_now_iso(),
            note="Free hosted tier",
        )
    return CostEstimate(
        target=target, estimated_usd=None, as_of=_now_iso(),
        note="Pricing not configured",
    )


def effective_budget_usd(
    route_max: Optional[float], settings: ComputeSettings
) -> Optional[float]:
    """The per-request budget in force: the route's own cap wins, else the
    global setting. ``None`` means no budget."""
    if route_max is not None:
        return route_max
    return settings.max_cost_usd_per_request


def within_budget(estimate: CostEstimate, budget_usd: Optional[float]) -> bool:
    """A target is allowed unless we *know* it exceeds the budget. An unknown
    cost is never auto-blocked — it's surfaced for the user to decide."""
    if budget_usd is None or not estimate.known:
        return True
    return (estimate.estimated_usd or 0.0) <= budget_usd
