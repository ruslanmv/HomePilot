import importlib

import pytest

expert_policies = importlib.import_module("app.expert.policies")
expert_router = importlib.import_module("app.expert.router")
expert_routes = importlib.import_module("app.expert.routes")
expert_schemas = importlib.import_module("app.expert.schemas")


def test_resolve_thinking_mode_auto_thresholds():
    assert expert_policies.resolve_thinking_mode("auto", 2).mode_used == "fast"
    assert expert_policies.resolve_thinking_mode("auto", 5).mode_used == "think"
    assert expert_policies.resolve_thinking_mode("auto", 9).mode_used == "heavy"


@pytest.mark.asyncio
async def test_dispatch_marks_fallback_metadata(monkeypatch):
    async def fail_call(*args, **kwargs):
        raise RuntimeError("remote down")

    async def fake_local(*args, **kwargs):
        return {"provider": "local", "choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(expert_router, "_call_provider", fail_call)
    monkeypatch.setattr(expert_router, "chat_local", fake_local)

    raw = await expert_router.dispatch([
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
    ], "groq")

    meta = expert_router.extract_dispatch_meta(raw)
    assert meta["fallback_applied"] is True
    assert meta["requested_provider"] == "groq"
    assert meta["provider_used"] == "local"


def test_compute_request_complexity_accounts_for_attachments_and_history():
    req = expert_schemas.ExpertChatRequest(
        query="hello",
        has_attachments=True,
        history=[expert_schemas.ExpertMessage(role="user", content=f"m{i}") for i in range(9)],
    )
    score = expert_routes._compute_request_complexity(req)
    base = expert_router.score_complexity("hello")
    assert score == min(base + 3, 10)


@pytest.mark.asyncio
async def test_low_budget_downgrades_heavy_to_think(monkeypatch):
    async def fake_think(*args, **kwargs):
        return {"final_answer": "think-answer", "steps": {}, "provider": "local", "model": "m"}

    async def fake_heavy(*args, **kwargs):
        raise AssertionError("heavy should not run when budgetTier=low")

    monkeypatch.setattr(expert_routes, "think", fake_think)
    monkeypatch.setattr(expert_routes, "heavy", fake_heavy)
    monkeypatch.setattr(expert_routes, "select_provider", lambda *_args, **_kwargs: "local")

    req = expert_schemas.ExpertChatRequest(
        query="Please deeply analyze and design this architecture with tradeoffs",
        thinking_mode="heavy",
        feature_hints={"budgetTier": "low"},
    )
    out = await expert_routes.expert_chat(req)

    assert out.thinking_mode_used == "think"
    assert out.strategy_used == "expert-thinking"
    assert any("downgraded heavy mode to think" in n for n in out.notices)
