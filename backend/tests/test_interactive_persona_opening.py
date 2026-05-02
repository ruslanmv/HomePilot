import asyncio
import warnings
from types import SimpleNamespace

from app.interactive.routes import _persona_opening as opening


def _cfg():
    return SimpleNamespace(llm_temperature=0.2, llm_max_tokens=120)


def _policy():
    return SimpleNamespace(timeout_s=1.0)


def test_run_llm_sync_parses_json(monkeypatch):
    async def _fake_chat(_messages, **_kwargs):
        return {
            "choices": [{
                "message": {
                    "content": '{"reply_text":"Hello there","scene_prompt":"smile softly"}',
                },
            }],
        }

    monkeypatch.setattr("app.llm.chat_ollama", _fake_chat)
    out = opening._run_llm_sync([{"role": "user", "content": "hi"}], _policy(), _cfg())
    assert isinstance(out, dict)
    assert out["reply_text"] == "Hello there"
    assert out["scene_prompt"] == "smile softly"


def test_run_llm_sync_inside_running_loop_has_no_unawaited_warning():
    async def _inner():
        with warnings.catch_warnings(record=True) as got:
            warnings.simplefilter("always")
            out = opening._run_llm_sync([], _policy(), _cfg())
        assert out is None
        assert not any("was never awaited" in str(w.message) for w in got)

    asyncio.run(_inner())

