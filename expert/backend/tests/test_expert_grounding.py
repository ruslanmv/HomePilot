"""Expert answers knowing today's date, and from HomePilot's web sources when the chat searched.

Fast mode answered "which day is today?" with its training date and "tell me the news" with
stale headlines: Expert's pipelines build their own prompts, and nothing put the date (or any
sources) in them. Now every system prompt Expert builds — fast, think and heavy — carries the
request's grounding (``app/expert/grounding.py``).
"""

import importlib
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _mods():
    return (importlib.import_module("app.expert.routes"), importlib.import_module("app.expert.grounding"),
            importlib.import_module("app.expert.router"), importlib.import_module("app.expert.thinking"),
            importlib.import_module("app.expert.heavy"))


def test_the_date_is_the_users_and_outside_a_request_nothing_changes():
    _, grounding, router, _, _ = _mods()
    line = grounding.date_line("Europe/Rome", now=datetime(2026, 10, 20, 15, 5, tzinfo=timezone.utc))
    assert "Tuesday, October 20, 2026, 17:05 (Europe/Rome)" in line
    assert grounding.apply("BASE") == "BASE"
    with grounding.using("Europe/Rome", "WEB SEARCH RESULTS …\n[1] Source"):
        prompt = router.build_messages("hi")[0]["content"]
        assert "Current date and time:" in prompt and "[1] Source" in prompt
    assert grounding.apply("BASE") == "BASE"


def test_fast_mode_sends_the_date_and_the_sources(monkeypatch):
    routes, _, _, _, _ = _mods()
    sent = []

    async def fake_dispatch(messages, provider, **kwargs):
        sent.append(messages)
        return {"choices": [{"message": {"content": "Today is Tuesday [1]."}}]}

    monkeypatch.setattr(routes, "dispatch", fake_dispatch)
    app = FastAPI()
    app.include_router(routes.router)
    r = TestClient(app).post("/v1/expert/chat", json={
        "query": "which day is today?", "thinking_mode": "fast", "client_timezone": "Europe/Rome",
        "context": "WEB SEARCH RESULTS — retrieved just now.\n[1] Rome time — time.test",
    })
    assert r.status_code == 200, r.text
    system = sent[0][0]["content"]
    assert "Current date and time:" in system and "(Europe/Rome)" in system
    assert "[1] Rome time — time.test" in system


def test_think_and_heavy_carry_it_into_every_step(monkeypatch):
    _, grounding, _, thinking, heavy = _mods()
    seen = []

    async def fake_dispatch(messages, provider, **kwargs):
        seen.append(messages[0]["content"])
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(thinking, "dispatch", fake_dispatch)
    monkeypatch.setattr(heavy, "dispatch", fake_dispatch)
    import asyncio

    async def run():
        with grounding.using("UTC", "[1] A source"):
            await thinking.think("what changed today?")
            await heavy.heavy("what changed today?")

    asyncio.run(run())
    assert len(seen) >= 4
    assert all("Current date and time:" in s and "[1] A source" in s for s in seen)
