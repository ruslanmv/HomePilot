"""Web search in the standard chat (app/web_search.py) and today's date in its prompt.

The chat used to answer "which day is today?" with its training date and "tell me the news"
with stale memories presented as current. Now every standard chat is told the date, and with
the chat's "Search the web" switch on it is handed current, numbered sources it must cite.

What is pinned:

* the date block, in the user's own time zone;
* sources: de-duplicated, capped per domain, the engine's order kept;
* reading: only readable text, only the passages that match, never a private address;
* the server reply: structured results preferred, the old prose still understood, and an
  unreachable server reported as unavailable — never as results;
* planning: a first message searched as typed, a follow-up rewritten (or, without a model,
  given the previous question's words);
* the chat itself: only the standard chat gets the date and the sources, and the reply
  carries them for the UI; a persona-style prompt is left exactly as it was.

No network: the search server and the model are stubbed.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest


def ws():
    from app import web_search

    return web_search


# ── the date ────────────────────────────────────────────────────────────────


def test_the_prompt_carries_today_in_the_users_zone():
    now = datetime(2026, 10, 20, 15, 5, tzinfo=timezone.utc)
    text = ws().current_time_context("Europe/Rome", now=now)
    assert "Tuesday, October 20, 2026, 17:05 (Europe/Rome)" in text
    assert "never invent recent events" in text


def test_an_unknown_zone_falls_back_to_the_servers():
    text = ws().current_time_context("Not/AZone", now=datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc))
    assert "2026" in text and "Not/AZone" not in text


# ── sources ─────────────────────────────────────────────────────────────────


def test_sources_are_deduplicated_and_capped_per_domain():
    results = [
        {"title": "A", "url": "https://www.example.org/a"},
        {"title": "A again", "url": "https://www.example.org/a#top"},
        {"title": "B", "url": "https://example.org/b"},
        {"title": "C", "url": "https://example.org/c"},          # third from one site: dropped
        {"title": "D", "url": "https://news.test/d", "snippet": "  lots   of   space "},
        {"title": "bad", "url": "ftp://files.test/x"},
    ]
    sources = ws().select_sources(results)
    assert [s.title for s in sources] == ["A", "B", "D"]
    assert [s.n for s in sources] == [1, 2, 3]
    assert sources[0].domain == "example.org"
    assert sources[2].snippet == "lots of space"


def test_reading_keeps_only_the_text_and_the_passages_that_match():
    html = """
      <html><head><title>T</title><script>var x = "Eiffel tower script noise noise noise";</script></head>
      <body><nav>Home · About · Contact · Eiffel menu entries that should never be read</nav>
      <p>The Eiffel Tower is 330 metres tall since a new antenna was added in 2022, the operator says.</p>
      <p>Paris has many bakeries, and this paragraph is about croissants rather than towers at all.</p>
      <footer>Copyright notice that is long enough to count as a paragraph of text here</footer></body></html>
    """
    paragraphs = ws().extract_paragraphs(html)
    assert any("330 metres" in p for p in paragraphs)
    assert not any("script noise" in p or "menu entries" in p or "Copyright" in p for p in paragraphs)
    best = ws().best_passages(paragraphs, "how tall is the eiffel tower", budget=120)
    assert best.startswith("The Eiffel Tower is 330 metres")
    assert "croissants" not in best


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "10.1.2.3", "192.168.0.10", "169.254.169.254", "::1"])
def test_private_and_internal_addresses_are_never_fetched(host):
    assert ws()._public_host(host) is False


def test_a_page_on_a_private_address_is_not_read():
    import httpx

    async def run():
        async with httpx.AsyncClient() as client:
            return await ws().read_page("http://127.0.0.1:9/secret", client)

    assert asyncio.run(run()) == []


# ── the search server ───────────────────────────────────────────────────────


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self.body


class FakeClient:
    def __init__(self, body=None, error=None):
        self.body, self.error, self.sent = body, error, []

    async def post(self, url, json=None):
        self.sent.append((url, json))
        if self.error:
            raise self.error
        return FakeResponse(self.body)


def test_structured_results_are_used_when_the_server_sends_them():
    client = FakeClient({"result": {"content": [{"type": "text", "text": "ignored"}], "structuredContent": {
        "results": [{"title": "T", "url": "https://a.test/x", "snippet": "s", "published": "2026-10-19"}]}}})
    out = asyncio.run(ws().search("q", recency_days=3, client=client))
    assert out == [{"title": "T", "url": "https://a.test/x", "snippet": "s", "published": "2026-10-19"}]
    url, body = client.sent[0]
    assert url.endswith(":9105/rpc")
    assert body["params"] == {"name": "hp.web.search", "arguments": {"query": "q", "limit": 10, "recency_days": 3}}


def test_an_older_servers_prose_is_still_understood():
    text = ("### Web Search Results (provider: searxng)\n\n1. **First**\n   - URL: https://a.test/1\n   - one\n\n"
            "2. **Second**\n   - URL: https://b.test/2\n")
    out = asyncio.run(ws().search("q", client=FakeClient({"result": {"content": [{"type": "text", "text": text}]}})))
    assert [(r["title"], r["url"], r["snippet"]) for r in out] == [("First", "https://a.test/1", "one"),
                                                                   ("Second", "https://b.test/2", "")]


def test_a_failed_search_is_unavailable_not_results():
    failed = FakeClient({"result": {"content": [{"type": "text", "text": "Web search failed (searxng): connection refused"}]}})
    with pytest.raises(ws().SearchUnavailable, match="SearXNG is not running"):
        asyncio.run(ws().search("q", client=failed))
    with pytest.raises(ws().SearchUnavailable, match="9105"):
        asyncio.run(ws().search("q", client=FakeClient(error=ConnectionError("refused"))))


# ── planning the query ──────────────────────────────────────────────────────


def test_a_first_message_is_searched_as_typed():
    async def chat(_):
        raise AssertionError("no model call for a first message")

    assert asyncio.run(ws().plan_query("latest Mars rover news", [("user", "latest Mars rover news")], chat=chat)) \
        == "latest Mars rover news"


def test_a_follow_up_is_rewritten_by_the_model():
    seen = []

    async def chat(messages):
        seen.append(messages)
        return "Perseverance rover news October 2026"

    history = [("user", "what's new with the Perseverance rover?"), ("assistant", "It found…"), ("user", "and yesterday?")]
    assert asyncio.run(ws().plan_query("and yesterday?", history, chat=chat)) == "Perseverance rover news October 2026"
    assert "Perseverance" in seen[0][1]["content"]


def test_without_a_model_a_follow_up_borrows_the_previous_question():
    async def broken(_):
        raise TimeoutError

    history = [("user", "Eiffel Tower height"), ("assistant", "330 m"), ("user", "and when was it built?")]
    assert asyncio.run(ws().plan_query("and when was it built?", history, chat=broken)) \
        == "Eiffel Tower height and when was it built?"


# ── the whole step and what the model is told ───────────────────────────────


def test_unavailable_tells_the_model_not_to_invent(monkeypatch):
    async def down(*a, **k):
        raise ws().SearchUnavailable("SearXNG is not running. Start it with `make start-searxng`.")

    monkeypatch.setattr(ws(), "search", down)
    ctx = asyncio.run(ws().gather("news today", []))
    assert ctx.status == "unavailable"
    block = ws().system_block(ctx)
    assert "could not search the web" in block and "Do not invent" in block
    public = ctx.public()
    assert public["hint"].startswith("SearXNG is not running")
    assert "out of date" in public["message"]


def test_sources_are_numbered_for_citation(monkeypatch):
    async def found(query, **kwargs):
        return [{"title": "Rover update", "url": "https://nasa.test/rover", "snippet": "It moved 20 m.",
                 "published": "2026-10-19T08:00:00"}]

    async def no_reading(sources, query, **kwargs):
        sources[0].excerpt = "The rover moved 20 metres on Sunday."

    monkeypatch.setattr(ws(), "search", found)
    monkeypatch.setattr(ws(), "read_sources", no_reading)
    ctx = asyncio.run(ws().gather("rover news today", []))
    block = ws().system_block(ctx)
    assert "[1] Rover update — nasa.test · 2026-10-19" in block
    assert "The rover moved 20 metres" in block
    assert "never invent a source" in block
    assert ctx.public()["sources"][0] == {"n": 1, "title": "Rover update", "url": "https://nasa.test/rover",
                                           "domain": "nasa.test", "snippet": "It moved 20 m.",
                                           "published": "2026-10-19T08:00:00", "read": True}


# ── the chat ────────────────────────────────────────────────────────────────


@pytest.fixture()
def chat_turn(monkeypatch):
    """Run one real `orchestrate` chat turn with storage, memory and the model stubbed."""
    from app import orchestrator

    sent, stored = [], []
    monkeypatch.setattr(orchestrator, "ensure_conversation_owner", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(orchestrator, "add_message", lambda cid, role, content, **k: stored.append((role, content, k)))
    monkeypatch.setattr(orchestrator, "get_recent", lambda cid, limit=8: [("user", "what is new in AI today?")])

    async def fake_route_chat(messages, **kwargs):
        sent.append(messages)
        return {"choices": [{"message": {"content": "Here is what changed [1]."}}]}

    monkeypatch.setattr(orchestrator, "route_chat", fake_route_chat)

    async def fake_gather(user_text, history, chat=None):
        return ws().WebContext(status="ok", query="AI news today", sources=[
            ws().Source(n=1, title="AI weekly", url="https://ai.test/weekly", domain="ai.test", snippet="s")])

    monkeypatch.setattr(ws(), "gather", fake_gather)

    def run(**kwargs):
        out = asyncio.run(orchestrator.orchestrate("what is new in AI today?", conversation_id="c-web",
                                                   incognito=True, memory_engine="off", **kwargs))
        return out, sent[-1], stored

    return run


def test_the_standard_chat_gets_the_date_and_the_sources(chat_turn):
    out, prompt, stored = chat_turn(web_search=True, client_timezone="Europe/Rome")
    system = prompt[0]["content"]
    assert "Current date and time:" in system and "(Europe/Rome)" in system
    assert "WEB SEARCH RESULTS" in system and "[1] AI weekly — ai.test" in system
    assert out["web_search"]["status"] == "ok"
    assert out["web_search"]["sources"][0]["url"] == "https://ai.test/weekly"
    # Kept with the reply, so a reopened chat still shows its sources.
    assistant = [s for s in stored if s[0] == "assistant"][-1]
    assert assistant[2]["media"]["web"]["query"] == "AI news today"


def test_without_the_switch_the_chat_gets_the_date_but_no_search(chat_turn):
    out, prompt, _ = chat_turn()
    assert "Current date and time:" in prompt[0]["content"]
    assert "WEB SEARCH" not in prompt[0]["content"]
    assert "web_search" not in out


def test_a_voice_personality_prompt_is_left_alone(chat_turn):
    _, prompt, _ = chat_turn(web_search=True, voice_system_prompt="You are Nova, a calm voice companion.")
    assert prompt[0]["content"].startswith("You are Nova")
    assert "WEB SEARCH" not in prompt[0]["content"]
    assert "Current date and time:" not in prompt[0]["content"]


def test_persona_agent_search_is_real_now(monkeypatch):
    """The persona agent's web_search tool used to return a fixed example.com result."""
    from app import search

    async def found(query, **kwargs):
        return [{"title": "Real", "url": "https://real.test/a", "snippet": "x"}]

    monkeypatch.setattr(ws(), "search", found)
    assert asyncio.run(search.web_search("anything")) == [
        {"title": "Real", "url": "https://real.test/a", "snippet": "x", "published_date": None}]

    async def down(*a, **k):
        raise ws().SearchUnavailable("down")

    monkeypatch.setattr(ws(), "search", down)
    assert asyncio.run(search.web_search("anything")) == []
