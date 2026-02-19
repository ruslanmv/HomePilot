<p align="center">
  <img src="../../../../assets/blog/homepilot-compatible-badge.svg" alt="HomePilot MCP Compatible" width="280" />
</p>

# MCP Executive Briefing

**Daily digests, weekly summaries, change tracking, and custom digests.**

| | |
| :--- | :--- |
| **Server name** | `homepilot-executive-briefing` |
| **Default port** | `9104` |
| **Protocol** | JSON-RPC 2.0 (MCP v1) |
| **Category** | Core Tool Server |

---

## What It Does

The Executive Briefing MCP server generates structured digests and summaries for your AI Persona. It produces daily and weekly briefings, tracks what changed since a given timestamp, and creates custom digests from any list of items — all tailored by audience (executive, team, or personal).

This is the server that powers: *"Give me the daily brief for the engineering team."*

---

## Tools

| Tool | Description |
| :--- | :--- |
| `hp.brief.daily` | Generate a daily digest (read-only) |
| `hp.brief.weekly` | Generate a weekly digest (read-only) |
| `hp.brief.what_changed_since` | Summarize changes since a timestamp (read-only) |
| `hp.brief.digest` | Create a custom digest from a list of items (read-only) |

All tools are read-only — no write gating required.

### Tool Details

**`hp.brief.daily`**
```json
{
  "audience": "team",
  "project_ids": ["project-alpha", "project-beta"],
  "max_items": 7
}
```
- `audience` — `executive`, `team`, or `personal`
- `project_ids` (array, optional) — Filter to specific projects
- `max_items` (integer, 3–15, default 7)

**`hp.brief.what_changed_since`**
```json
{
  "since": "2026-02-17T00:00:00Z",
  "project_ids": ["project-alpha"]
}
```
Returns a structured change summary (new files, updated descriptions, configuration changes).

**`hp.brief.digest`**
```json
{
  "items": ["Deployment completed", "3 bugs fixed", "New feature launched"],
  "audience": "executive"
}
```
Transforms a list of items into a formatted digest (up to 20 items).

---

## Installation

### As Part of HomePilot

```bash
AGENTIC=1 make start
```

### Standalone

```bash
PYTHONPATH=/path/to/HomePilot uvicorn \
  agentic.integrations.mcp.executive_briefing_server:app \
  --host 0.0.0.0 --port 9104
```

---

## API Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/health` | GET | Health check |
| `/rpc` | POST | JSON-RPC 2.0 endpoint |

---

## Project Structure

```
executive-briefing/
├── pyproject.toml                       # Project metadata
└── (server code in parent directory)
    └── executive_briefing_server.py     # Tool definitions and handlers
```

---

## Part of the HomePilot Ecosystem

This is one of the 5 core MCP tool servers that ship with HomePilot.

| Core Server | Port | Purpose |
| :--- | :--- | :--- |
| Personal Assistant | 9101 | Task management, day planning |
| Knowledge | 9102 | Document search, RAG queries |
| Decision Copilot | 9103 | Decision frameworks, risk assessment |
| **Executive Briefing** | 9104 | Daily/weekly digests, change summaries |
| Web Search | 9105 | Real-time web research |

---

<p align="center">
  <b>HomePilot</b> — Your AI. Your data. Your rules.<br>
  <a href="https://github.com/ruslanmv/HomePilot">GitHub</a> · <a href="../../../../docs/INTEGRATIONS.md">Integrations Guide</a>
</p>
