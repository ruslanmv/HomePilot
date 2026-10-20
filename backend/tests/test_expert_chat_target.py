"""Expert answers from the chat model the user picked.

Reported (20 Oct 2026): with OllaBridge Local connected and `openwebui/internal-gemma4-31b`
selected for chat, a message in a reasoning mode failed with

    Expert pipeline error: Server error '500 Internal Server Error' for url
    'http://localhost:11434/api/chat'

— Expert ignored the selection and called Ollama's default model. The client now sends the
selection as `target`, and every Expert step answers from it.

Expert is loaded here the way `app/main.py` loads it — as the top-level package
`homepilot_expert` — because that is where a relative import out of the package breaks.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

EXPERT_DIR = Path(__file__).resolve().parents[2] / "expert" / "backend" / "app" / "expert"


def _expert():
    if "homepilot_expert" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "homepilot_expert", EXPERT_DIR / "__init__.py", submodule_search_locations=[str(EXPERT_DIR)]
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["homepilot_expert"] = module
        spec.loader.exec_module(module)
    return (
        sys.modules["homepilot_expert"],
        importlib.import_module("homepilot_expert.router"),
        importlib.import_module("homepilot_expert.target"),
        importlib.import_module("homepilot_expert.providers"),
    )


@pytest.fixture()
def expert():
    package, router, target, providers = _expert()
    return package, router, target, providers


GATEWAY = {"provider": "openai_compat", "base_url": "http://localhost:11435/v1",
           "model": "openwebui/internal-gemma4-31b", "api_key": "local-key"}
MESSAGES = [{"role": "user", "content": "Hello"}]


class TestTheTarget:
    def test_a_gateway_selection_is_a_target(self, expert):
        _, _, target, _ = expert
        chosen = target.from_request(GATEWAY)
        assert chosen.provider == "openai_compat"
        assert chosen.base_url == "http://localhost:11435/v1"
        assert chosen.model == "openwebui/internal-gemma4-31b"
        assert "local-key" not in repr(chosen)

    @pytest.mark.parametrize("raw", [
        None,
        {"provider": "ollama"},                      # Expert's own defaults already mean this
        {"provider": "openai_compat", "model": "x"},  # nowhere to send it
    ])
    def test_nothing_usable_is_no_target(self, expert, raw):
        _, _, target, _ = expert
        assert target.from_request(raw) is None


class TestDispatch:
    def test_local_answers_from_the_chosen_gateway(self, expert, monkeypatch):
        _, router, target, _ = expert
        seen = {}

        async def fake_compat(messages, **kwargs):
            seen.update(kwargs)
            return {"choices": [{"message": {"content": "hi from gemma"}}], "provider": kwargs["provider_label"],
                    "model": kwargs["model"]}

        async def no_ollama(*args, **kwargs):
            raise AssertionError("Ollama must not be called when a gateway model is chosen")

        monkeypatch.setattr(router, "chat_openai_compat", fake_compat)
        monkeypatch.setattr(router, "chat_local", no_ollama)

        async def scenario():
            with target.using(target.from_request(GATEWAY)):
                return await router.dispatch(MESSAGES, "local")

        raw = asyncio.run(scenario())
        assert raw["choices"][0]["message"]["content"] == "hi from gemma"
        assert seen["base_url"] == "http://localhost:11435/v1"
        assert seen["model"] == "openwebui/internal-gemma4-31b"
        assert seen["api_key"] == "local-key"

    def test_a_failing_cloud_provider_falls_back_to_the_chosen_model_not_ollama(self, expert, monkeypatch):
        _, router, target, _ = expert

        async def broken(*args, **kwargs):
            raise RuntimeError("groq is down")

        async def fake_compat(messages, **kwargs):
            return {"choices": [{"message": {"content": "fallback ok"}}], "provider": "openai_compat", "model": "m"}

        monkeypatch.setattr(router, "chat_groq", broken)
        monkeypatch.setattr(router, "chat_openai_compat", fake_compat)

        async def scenario():
            with target.using(target.from_request(GATEWAY)):
                return await router.dispatch(MESSAGES, "groq")

        raw = asyncio.run(scenario())
        assert raw["choices"][0]["message"]["content"] == "fallback ok"

    def test_an_ollama_selection_uses_that_model(self, expert, monkeypatch):
        _, router, target, _ = expert
        seen = {}

        async def fake_local(messages, **kwargs):
            seen.update(kwargs)
            return {"choices": [{"message": {"content": "ok"}}], "provider": "local", "model": kwargs["model"]}

        monkeypatch.setattr(router, "chat_local", fake_local)

        async def scenario():
            chosen = target.from_request({"provider": "ollama", "model": "deepseek-r1:latest",
                                          "base_url": "http://localhost:11434"})
            with target.using(chosen):
                return await router.dispatch(MESSAGES, "local")

        asyncio.run(scenario())
        assert seen["model"] == "deepseek-r1:latest"
        assert seen["base_url"] == "http://localhost:11434"

    def test_without_a_target_nothing_changes(self, expert, monkeypatch):
        _, router, _, _ = expert
        seen = {}

        async def fake_local(messages, **kwargs):
            seen.update(kwargs)
            return {"choices": [{"message": {"content": "ok"}}], "provider": "local", "model": "default"}

        monkeypatch.setattr(router, "chat_local", fake_local)
        asyncio.run(router.dispatch(MESSAGES, "local"))
        assert "base_url" not in seen


class TestTheVoice:
    def test_the_assistant_does_not_announce_itself(self, expert):
        # "Hello! I am Expert, your HomePilot assistant." — the old prompt named the pipeline
        # as if it were a persona, and models introduced themselves by that name.
        config = importlib.import_module("homepilot_expert.config")
        prompt = config.EXPERT_SYSTEM_PROMPT
        assert "You are Expert" not in prompt
        assert "Do not introduce yourself" in prompt
        assert "language the user writes in" in prompt


class TestTheGatewayCall:
    def test_the_gateways_own_error_is_kept(self, expert, monkeypatch):
        _, _, _, providers = expert

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url == "http://localhost:11435/v1/chat/completions"
            assert request.headers["authorization"] == "Bearer local-key"
            return httpx.Response(500, json={"error": {"message": "upstream model is loading"}})

        real_client = httpx.AsyncClient
        monkeypatch.setattr(providers.httpx, "AsyncClient",
                            lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
        with pytest.raises(RuntimeError, match="answered HTTP 500: upstream model is loading"):
            asyncio.run(providers.chat_openai_compat(MESSAGES, base_url="http://localhost:11435/v1",
                                                     model="m", api_key="local-key"))


class TestTheRoute:
    def test_a_fast_message_with_a_target_never_reaches_ollama(self, expert, monkeypatch):
        package, router, _, _ = expert

        async def fake_compat(messages, **kwargs):
            return {"choices": [{"message": {"content": "Hello! How can I help?"}}],
                    "provider": kwargs["provider_label"], "model": kwargs["model"]}

        async def no_ollama(*args, **kwargs):
            raise AssertionError("Ollama must not be called")

        monkeypatch.setattr(router, "chat_openai_compat", fake_compat)
        monkeypatch.setattr(router, "chat_local", no_ollama)
        app = FastAPI()
        app.include_router(package.router)
        res = TestClient(app).post("/v1/expert/chat", json={
            "query": "Hello", "provider": "auto", "thinking_mode": "fast", "target": GATEWAY,
        })
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["content"] == "Hello! How can I help?"
        assert body["provider_used"] == "openai_compat"
        assert body["model_used"] == "openwebui/internal-gemma4-31b"
