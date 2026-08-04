"""PR 5 — cost-aware routing: estimates, budgets, and route explanations."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---- estimates ----------------------------------------------------------

def test_own_hardware_is_free_by_default(compute_db):
    from app.compute import cost, registry
    s = registry.load_settings()
    for t in ("local", "ollabridge_cloud", "device:colab", "source:my-vllm"):
        est = cost.estimate_target(t, "chat", s)
        assert est.estimated_usd == 0.0 and est.known

    # A free hosted alias is free; an unpriced hosted provider is unknown.
    assert cost.estimate_target("provider:free-best", "chat", s).estimated_usd == 0.0
    assert cost.estimate_target("provider:groq", "chat", s).known is False


def test_catalog_override_wins(compute_db):
    from app.compute import cost, registry
    s = registry.load_settings()
    s.cost_catalog = {"provider:groq": {"usd": 0.02, "per_unit": "request", "as_of": "2026-08-01", "note": "list"}}
    registry.save_settings(s)
    est = cost.estimate_target("provider:groq", "chat", registry.load_settings())
    assert est.estimated_usd == 0.02 and est.as_of == "2026-08-01" and est.per_unit == "request"


def test_within_budget_semantics():
    from app.compute import cost
    from app.compute.cost import CostEstimate
    assert cost.within_budget(CostEstimate("x", estimated_usd=None), 1.0) is True   # unknown allowed
    assert cost.within_budget(CostEstimate("x", estimated_usd=0.5), 1.0) is True
    assert cost.within_budget(CostEstimate("x", estimated_usd=2.0), 1.0) is False
    assert cost.within_budget(CostEstimate("x", estimated_usd=2.0), None) is True    # no budget


# ---- budget filtering in resolution -------------------------------------

def test_route_budget_drops_expensive_device(compute_db):
    from app.compute import registry, policies
    from app.compute.schemas import ModelRoute
    s = registry.load_settings()
    s.cost_catalog = {"device:colab": {"usd": 2.0}}
    registry.save_settings(s)
    registry.upsert_route(ModelRoute(
        modality="chat", model_id="m", primary_target="device:colab",
        fallback_targets=["local"], strategy="pinned", max_cost_usd=1.0,
    ))
    targets = policies.resolve_targets("chat", "m")
    assert "device:colab" not in targets   # 2.0 > 1.0 budget
    assert "local" in targets              # free fallback survives


def test_global_budget_applies_without_route(compute_db):
    from app.compute import registry, policies
    from app.compute.schemas import ModalityDefault
    s = registry.load_settings()
    s.max_cost_usd_per_request = 1.0
    s.cost_catalog = {"device:rig": {"usd": 5.0}}
    s.modality_defaults["chat"] = ModalityDefault(
        modality="chat", strategy="pinned", target="device:rig",
        fallback_targets=["local"], privacy="private_nodes")
    registry.save_settings(s)
    targets = policies.resolve_targets("chat", "any-model")
    assert "device:rig" not in targets and "local" in targets


# ---- explanations -------------------------------------------------------

def test_explain_reports_costs_and_budget(compute_db):
    from app.compute import registry, policies
    from app.compute.schemas import ModelRoute
    s = registry.load_settings()
    s.cost_catalog = {"provider:groq": {"usd": 5.0}}
    registry.save_settings(s)
    registry.upsert_route(ModelRoute(
        modality="chat", model_id="m", primary_target="provider:groq",
        fallback_targets=["local"], strategy="pinned",
        privacy="hosted_allowed", max_cost_usd=1.0,
    ))
    ex = policies.explain("chat", "m")
    assert ex["budget_usd"] == 1.0
    by_target = {c["target"]: c for c in ex["costs"]}
    # The expensive hosted option is shown, priced, and flagged over budget.
    assert by_target["provider:groq"]["estimated_usd"] == 5.0
    assert by_target["provider:groq"]["over_budget"] is True
    assert by_target["provider:groq"]["selected"] is False
    # Local is free, selected, within budget.
    assert by_target["local"]["estimated_usd"] == 0.0
    assert by_target["local"]["selected"] is True
