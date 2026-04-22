import importlib

import pytest

expert_router = importlib.import_module("app.expert.router")
expert_thinking = importlib.import_module("app.expert.thinking")
expert_heavy = importlib.import_module("app.expert.heavy")


def test_score_complexity_and_provider_selection_local_only(monkeypatch):
    monkeypatch.setattr(expert_router, "available_expert_providers", lambda: ["local"])

    simple = "hi"
    complex_q = "Please analyze and design a scalable architecture with tradeoffs and code examples."

    assert expert_router.score_complexity(simple) <= expert_router.score_complexity(complex_q)
    assert expert_router.select_provider(simple, preferred="auto") == "local"
    assert expert_router.select_provider(complex_q, preferred="auto") == "local"


def test_build_messages_includes_system_history_and_user():
    msgs = expert_router.build_messages(
        "final question",
        history=[
            {"role": "user", "content": "prev user"},
            {"role": "assistant", "content": "prev assistant"},
        ],
        system_prompt="system-test",
    )

    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "system-test"
    assert msgs[-1] == {"role": "user", "content": "final question"}
    assert len(msgs) == 4


@pytest.mark.asyncio
async def test_think_pipeline_returns_expected_steps(monkeypatch):
    async def fake_dispatch(messages, provider, **kwargs):
        prompt = messages[-1]["content"]
        if "Analysis:" in prompt and "Problem:" in prompt:
            text = "analysis-output"
        elif "Step-by-step plan:" in prompt:
            text = "plan-output"
        elif "Final answer:" in prompt:
            text = "solution-output"
        else:
            text = "fallback-output"
        return {"choices": [{"message": {"content": text}}], "provider": provider, "model": "test-model"}

    monkeypatch.setattr(expert_thinking, "dispatch", fake_dispatch)

    out = await expert_thinking.think("analyze this", provider="local", with_critique=False)

    assert out["final_answer"] == "solution-output"
    assert out["steps"]["analysis"] == "analysis-output"
    assert out["steps"]["plan"] == "plan-output"
    assert out["steps"]["solution"] == "solution-output"


@pytest.mark.asyncio
async def test_heavy_pipeline_uses_validator_correction(monkeypatch):
    async def fake_dispatch(messages, provider, **kwargs):
        system = messages[0]["content"]
        if "deep research agent" in system:
            text = "research-output"
        elif "logical reasoning agent" in system:
            text = "reasoning-output"
        elif "synthesis agent" in system:
            text = "synthesis-output"
        else:
            text = "CORRECTION: corrected-final-answer"
        return {"choices": [{"message": {"content": text}}], "provider": provider}

    monkeypatch.setattr(expert_heavy, "dispatch", fake_dispatch)

    out = await expert_heavy.heavy("hard problem", provider="local")

    assert out["agents"]["research"] == "research-output"
    assert out["agents"]["reasoning"] == "reasoning-output"
    assert out["agents"]["synthesis"] == "synthesis-output"
    assert out["final_answer"] == "corrected-final-answer"
