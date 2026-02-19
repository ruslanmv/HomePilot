<p align="center">
  <img src="../../../../assets/blog/homepilot-compatible-badge.svg" alt="HomePilot MCP Compatible" width="280" />
</p>

# MCP Web Search

**Real-time web search with pluggable providers: SearXNG (home) or Tavily (enterprise).**

| | |
| :--- | :--- |
| **Server name** | `homepilot-web-search` |
| **Default port** | `9105` |
| **Protocol** | JSON-RPC 2.0 (MCP v1) |
| **Category** | Core Tool Server |

---

## What It Does

The Web Search MCP server gives your AI Persona the ability to search the web in real time. It ships with two pluggable search providers:

- **SearXNG** (default, home mode) — Self-hosted metasearch engine. No API keys required. Privacy-first.
- **Tavily** (enterprise mode) — Commercial search API with high-quality results. Requires an API key.

This is the server that powers: *"Search the web for the latest React 19 migration guide."*

---

## Tools

| Tool | Description |
| :--- | :--- |
| `hp.web.search` | Search the web using the configured provider |
| `hp.web.fetch` | Fetch raw content from a URL |

### Tool Details

**`hp.web.search`**
```json
{
  "query": "React 19 migration guide",
  "limit": 5,
  "recency_days": 30,
  "domains": ["react.dev", "github.com"]
}
```
- `query` (string, required) — Search query
- `limit` (integer, default 5) — Maximum results
- `recency_days` (integer, default 30) — Filter by recency (maps to time_range for SearXNG)
- `domains` (array of strings, optional) — Restrict to specific domains

Returns results with title, URL, snippet, and source provider.

---

## Search Providers

### SearXNG (Home Mode — Default)

Self-hosted metasearch engine that aggregates results from multiple search engines without tracking.

**Setup:**
1. Deploy SearXNG (e.g., via Docker: `docker run -p 8080:8080 searxng/searxng`)
2. Set `SEARXNG_BASE_URL=http://localhost:8080` in your environment
3. No API keys needed

**Features:**
- Privacy-first: no query logging
- Configurable search engines
- SafeSearch enabled by default
- Time-range filtering (day, week, month, year)

### Tavily (Enterprise Mode)

Commercial search API optimized for AI applications.

**Setup:**
1. Get an API key from [tavily.com](https://tavily.com)
2. Set `WEB_SEARCH_PROVIDER=tavily` and `TAVILY_API_KEY=tvly-...`

**Features:**
- High-quality, AI-optimized results
- Domain filtering
- Search depth control (basic/advanced)

---

## Installation

### As Part of HomePilot

```bash
AGENTIC=1 make start
```

### Standalone

```bash
PYTHONPATH=/path/to/HomePilot uvicorn \
  agentic.integrations.mcp.web_search_server:app \
  --host 0.0.0.0 --port 9105
```

---

## Configuration

| Variable | Default | Description |
| :--- | :--- | :--- |
| `WEB_SEARCH_PROVIDER` | `searxng` | Provider: `searxng` or `tavily` |
| `SEARXNG_BASE_URL` | `http://localhost:8080` | SearXNG instance URL |
| `TAVILY_API_KEY` | *(empty)* | Tavily API key (required for tavily provider) |
| `WEB_SEARCH_TIMEOUT` | `12.0` | HTTP timeout in seconds |

---

## API Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/health` | GET | Health check |
| `/rpc` | POST | JSON-RPC 2.0 endpoint |

---

## Project Structure

```
web_search/
├── __init__.py
├── config.py         # Environment-based configuration
├── providers.py      # SearxngProvider and TavilyProvider implementations
└── (server entry point in parent directory)
    └── web_search_server.py
```

### Architecture

```
Request → web_search_server.py → providers.get_provider()
                                    ├── SearxngProvider.search()  → SearXNG /search?format=json
                                    └── TavilyProvider.search()   → api.tavily.com/search
```

---

## Part of the HomePilot Ecosystem

This is one of the 5 core MCP tool servers that ship with HomePilot.

| Core Server | Port | Purpose |
| :--- | :--- | :--- |
| Personal Assistant | 9101 | Task management, day planning |
| Knowledge | 9102 | Document search, RAG queries |
| Decision Copilot | 9103 | Decision frameworks, risk assessment |
| Executive Briefing | 9104 | Daily/weekly digests, change summaries |
| **Web Search** | 9105 | Real-time web research |

---

<p align="center">
  <b>HomePilot</b> — Your AI. Your data. Your rules.<br>
  <a href="https://github.com/ruslanmv/HomePilot">GitHub</a> · <a href="../../../../docs/INTEGRATIONS.md">Integrations Guide</a>
</p>
