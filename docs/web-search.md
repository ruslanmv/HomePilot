# Web search in chat

**Chat → + → Search the web** (or **Chat settings → Search the web**) lets a standard chat answer
from current web pages, with numbered sources. It is per chat and off by default. Persona and
project chats keep their own setup and do not show the switch; the persona agent's own
`web_search` tool now uses the same search instead of a placeholder.

Every standard chat — switch on or off — is also told today's date and time in the browser's
time zone, so "which day is today?" is answered correctly and the model is told not to invent
recent events when it has no sources.

## How an answer is grounded

`backend/app/web_search.py`, the pattern search-grounded assistants use:

1. **Plan** — a follow-up ("and yesterday?") is rewritten into a standalone query by the chat
   model (8 s limit; a first message is searched as typed, and without a model a follow-up
   borrows the previous question's words).
2. **Search** — `hp.web.search` on the web-search MCP server (`:9105`), which asks SearXNG
   (default) or Tavily. Questions about today, news, prices or scores ask for recent results;
   others search every date. Results are de-duplicated and capped at two per site.
3. **Read** — up to six pages are fetched at once (6 s, 1.5 MB each) and the relevant passages
   of the first three that can be read are kept. Private, loopback and link-local addresses
   are refused at every redirect.
4. **Answer** — the model gets the sources as `[1]…[n]` with instructions to cite them, never
   to invent a source, and to say when they do not answer. The reply carries the same list:
   the chat shows "Searched the web for … · N sources", source chips, and every `[n]` links to
   its page. The sources are stored with the message, so a reopened chat still shows them.

When search cannot run, the model is told to say so and not to make up current events, and
the answer carries an amber note with what to start.

## Running it

```bash
make start-searxng      # SearXNG in Docker on 127.0.0.1:8899 (SEARXNG_PORT=… to move it)
make stop-searxng
```

The web-search MCP server on `:9105` starts with `make start`. It reads `SEARXNG_BASE_URL`
(default `http://127.0.0.1:8899`); keep it in step if you change `SEARXNG_PORT`. For Tavily set
`WEB_SEARCH_PROVIDER=tavily` and `TAVILY_API_KEY`. `GET /v1/web-search/status` reports whether
search can run and what is missing; Chat settings shows the same.

SearXNG's settings (`agentic/ops/compose/searxng/settings.yml`) turn on its JSON API, safe
search "moderate" and no bot limiter; it listens on 127.0.0.1 only, and its secret is generated
when the container is created. Searches leave this computer through SearXNG to the engines it
queries.

Tests: `backend/tests/test_web_search.py`, `frontend/src/test/chatWebSearch.test.tsx`.
