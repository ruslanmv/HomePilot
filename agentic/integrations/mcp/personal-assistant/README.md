<p align="center">
  <img src="../../../../assets/blog/homepilot-compatible-badge.svg" alt="HomePilot MCP Compatible" width="280" />
</p>

# MCP Personal Assistant

**Task management, day planning, and personal memory search.**

| | |
| :--- | :--- |
| **Server name** | `homepilot-personal-assistant` |
| **Default port** | `9101` |
| **Protocol** | JSON-RPC 2.0 (MCP v1) |
| **Category** | Core Tool Server |

---

## What It Does

The Personal Assistant MCP server provides your AI Persona with personal productivity tools. It can search your personal notes and memory, and help you plan your day with structured time-blocking and priority frameworks.

This is the core server that powers: *"Search my notes for the project requirements"* and *"Plan my day around these three meetings."*

---

## Tools

| Tool | Description |
| :--- | :--- |
| `hp.personal.search` | Search personal notes and memory |
| `hp.personal.plan_day` | Draft a structured day plan with optional constraints |

### Tool Details

**`hp.personal.search`**
```json
{
  "query": "project requirements",
  "limit": 10
}
```
- `query` (string, required) — Search query
- `limit` (integer, 1–50, default 10) — Maximum results

**`hp.personal.plan_day`**
```json
{
  "title": "Monday Sprint Planning",
  "constraints": ["standup at 9am", "client call at 2pm"]
}
```
- `title` (string, required) — Plan title
- `constraints` (array of strings, optional) — Time blocks, meetings, or priorities to work around

Returns a structured 5-step day plan:
1. Clarify top 1–3 priorities
2. Block two focus sessions (45–90 minutes)
3. Admin sweep (messages + calendar)
4. Pick one small win for momentum
5. End-of-day 5-minute review

---

## Installation

### As Part of HomePilot

This server starts automatically when you launch HomePilot with agentic mode:

```bash
AGENTIC=1 make start
```

### Standalone

```bash
PYTHONPATH=/path/to/HomePilot uvicorn \
  agentic.integrations.mcp.personal_assistant_server:app \
  --host 0.0.0.0 --port 9101
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
personal-assistant/
├── pyproject.toml                      # Project metadata
└── (server code in parent directory)
    └── personal_assistant_server.py    # Tool definitions and handlers
```

---

## Part of the HomePilot Ecosystem

This is one of the 5 core MCP tool servers that ship with HomePilot. It connects through the **Context Forge** gateway (port 4444) and is available to every Persona in linked mode.

| Core Server | Port | Purpose |
| :--- | :--- | :--- |
| **Personal Assistant** | 9101 | Task management, day planning |
| Knowledge | 9102 | Document search, RAG queries |
| Decision Copilot | 9103 | Decision frameworks, risk assessment |
| Executive Briefing | 9104 | Daily/weekly digests, change summaries |
| Web Search | 9105 | Real-time web research |

---

<p align="center">
  <b>HomePilot</b> — Your AI. Your data. Your rules.<br>
  <a href="https://github.com/ruslanmv/HomePilot">GitHub</a> · <a href="../../../../docs/INTEGRATIONS.md">Integrations Guide</a>
</p>
