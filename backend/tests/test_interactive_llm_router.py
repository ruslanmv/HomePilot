"""
Tests for ``app.interactive.llm_router`` — Enterprise Settings
chat model resolver + call_prompt dispatcher.

Coverage:

* ``resolve_current_chat_model`` reads env at call time, not at
  import time: changing ``OLLAMA_MODEL`` between calls is
  reflected in the next resolution.
* INTERACTIVE-scoped env overrides take precedence over the
  generic ones (so ops can force a smaller model for planning
  without touching the chat provider).
* Explicit override arguments trump every env source.
* Unknown providers fall through to the ollama defaults so the
  dispatcher still has something to try.
* ``call_prompt`` routes to ``chat_ollama`` with
  ``response_format`` for an ollama provider and forwards
  ``policy.timeout_s`` as the asyncio deadline.
* Non-ollama providers route through ``llm.chat`` WITHOUT
  ``response_format`` (since that kwarg is ollama-only).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from app.interactive.llm_router import (
    ChatModel,
    call_prompt,
    resolve_current_chat_model,
)
from app.interactive.prompts import PromptPolicy, RenderedPrompt


# ── resolve_current_chat_model ────────────────────────────────

def test_interactive_override_beats_global_env(monkeypatch):
    monkeypatch.setenv("DEFAULT_PROVIDER", "openai_compat")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3:8b")
    monkeypatch.setenv("INTERACTIVE_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("INTERACTIVE_LLM_MODEL", "huihui_ai/qwen3-abliterated:4b")

    m = resolve_current_chat_model()
    assert m.provider == "ollama"
    assert m.model == "huihui_ai/qwen3-abliterated:4b"


def test_global_env_used_when_interactive_unset(monkeypatch):
    monkeypatch.delenv("INTERACTIVE_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("INTERACTIVE_LLM_MODEL", raising=False)
    monkeypatch.delenv("INTERACTIVE_LLM_BASE_URL", raising=False)
    monkeypatch.setenv("DEFAULT_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3:8b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://host:11434")

    m = resolve_current_chat_model()
    assert m.provider == "ollama"
    assert m.model == "llama3:8b"
    assert m.base_url == "http://host:11434"


def test_model_is_read_live_not_at_import(monkeypatch):
    monkeypatch.setenv("DEFAULT_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "first-model")
    first = resolve_current_chat_model()
    assert first.model == "first-model"

    monkeypatch.setenv("OLLAMA_MODEL", "second-model")
    second = resolve_current_chat_model()
    assert second.model == "second-model"


def test_explicit_overrides_beat_env(monkeypatch):
    monkeypatch.setenv("DEFAULT_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "env-model")
    m = resolve_current_chat_model(
        provider_override="ollama",
        model_override="arg-model",
        base_url_override="http://arg:1234",
    )
    assert m.model == "arg-model"
    assert m.base_url == "http://arg:1234"


def test_unknown_provider_falls_back_to_ollama_defaults(monkeypatch):
    monkeypatch.setenv("DEFAULT_PROVIDER", "watsonx")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("INTERACTIVE_LLM_MODEL", raising=False)
    m = resolve_current_chat_model()
    # Provider is normalised to the raw env value; model falls
    # through to the ollama default so the downstream dispatcher
    # still has a plausible model string to try.
    assert m.provider == "watsonx"
    assert m.model == "llama3:8b"


def test_openai_compat_branch_reads_llm_model(monkeypatch):
    monkeypatch.setenv("DEFAULT_PROVIDER", "openai_compat")
    monkeypatch.delenv("INTERACTIVE_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("INTERACTIVE_LLM_MODEL", raising=False)
    monkeypatch.setenv("LLM_MODEL", "vllm-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm:8001/v1")
    m = resolve_current_chat_model()
    assert m.provider == "openai_compat"
    assert m.model == "vllm-model"
    assert m.base_url == "http://vllm:8001/v1"


def test_chat_model_describe_includes_provider_and_model():
    cm = ChatModel(provider="ollama", model="llama3:8b", base_url=None)
    assert cm.describe() == "ollama:llama3:8b"


# ── call_prompt dispatch ──────────────────────────────────────

class _CapturedCall:
    """Shared spy so the fakes can record what was invoked."""

    def __init__(self) -> None:
        self.target: str = ""
        self.messages: List[Dict[str, Any]] = []
        self.kwargs: Dict[str, Any] = {}


def _fake_rp(prompt_id: str = "demo") -> RenderedPrompt:
    return RenderedPrompt(
        prompt_id=prompt_id, version="1.0.0",
        system="sys text", user="user text",
    )


def _install_fakes(monkeypatch, captured: _CapturedCall) -> None:
    """Patch via string paths so we resolve the live ``app.llm``
    module from ``sys.modules`` — other tests in the suite purge
    + re-import ``app.*`` via the ``app`` fixture, which can leave
    a stale reference if we captured the module at import time.
    """
    import app.llm as llm_mod  # resolved once per call, fresh

    async def fake_chat_ollama(messages, **kw):
        captured.target = "chat_ollama"
        captured.messages = list(messages)
        captured.kwargs = dict(kw)
        return {"choices": [{"message": {"content": "ok"}}]}

    async def fake_chat(messages, **kw):
        captured.target = "chat"
        captured.messages = list(messages)
        captured.kwargs = dict(kw)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(llm_mod, "chat_ollama", fake_chat_ollama)
    monkeypatch.setattr(llm_mod, "chat", fake_chat)


def test_call_prompt_ollama_passes_response_format(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("INTERACTIVE_LLM_MODEL", "qwen:1.5b")
    captured = _CapturedCall()
    _install_fakes(monkeypatch, captured)

    policy = PromptPolicy(response_format="json", timeout_s=5.0)
    asyncio.run(call_prompt(_fake_rp(), policy))

    assert captured.target == "chat_ollama"
    assert captured.kwargs.get("response_format") == "json"
    assert captured.kwargs.get("model") == "qwen:1.5b"
    assert captured.messages[0]["content"] == "sys text"
    assert captured.messages[1]["content"] == "user text"


def test_call_prompt_non_ollama_omits_response_format(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_MODEL", "vllm-local")
    captured = _CapturedCall()
    _install_fakes(monkeypatch, captured)

    policy = PromptPolicy(response_format="json", timeout_s=5.0)
    asyncio.run(call_prompt(_fake_rp(), policy))

    assert captured.target == "chat"
    assert "response_format" not in captured.kwargs
    assert captured.kwargs.get("provider") == "openai_compat"
    assert captured.kwargs.get("model") == "vllm-local"


def test_call_prompt_respects_policy_timeout(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("INTERACTIVE_LLM_MODEL", "slow:1b")

    async def hang(*_a, **_kw):
        await asyncio.sleep(5)
        return {"choices": [{"message": {"content": "late"}}]}

    import app.llm as llm_mod  # fresh ref; see _install_fakes comment
    monkeypatch.setattr(llm_mod, "chat_ollama", hang)
    policy = PromptPolicy(timeout_s=0.05, response_format=None)
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(call_prompt(_fake_rp(), policy))
