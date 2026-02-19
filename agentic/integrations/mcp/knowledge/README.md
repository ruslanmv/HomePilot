<p align="center">
  <img src="../../../../assets/blog/homepilot-compatible-badge.svg" alt="HomePilot MCP Compatible" width="280" />
</p>

# MCP Knowledge

**Workspace search, document retrieval, RAG-style Q&A, and project summaries.**

| | |
| :--- | :--- |
| **Server name** | `homepilot-knowledge` |
| **Default port** | `9102` |
| **Protocol** | JSON-RPC 2.0 (MCP v1) |
| **Category** | Core Tool Server |

---

## What It Does

The Knowledge MCP server is the retrieval-augmented generation (RAG) backbone of HomePilot. It searches across your projects, documents, and notes, fetches documents by ID, answers questions with source citations, and summarizes project state.

This is the server that powers: *"What did we decide about the API migration?"* — and returns an answer with links to the source documents.

---

## Tools

| Tool | Description |
| :--- | :--- |
| `hp.search_workspace` | Search across projects, docs, and notes |
| `hp.get_document` | Fetch a document by ID |
| `hp.answer_with_sources` | Answer a question using sources and return citations |
| `hp.summarize_project` | Summarize a project's current state |

### Tool Details

**`hp.search_workspace`**
```json
{
  "query": "API migration plan",
  "scope": "all",
  "limit": 10
}
```
- `query` (string, required) — Search query
- `scope` (string: `project` | `docs` | `all`, default `all`) — Search scope
- `limit` (integer, 1–50, default 10) — Maximum results

Returns results with title, snippet, source type, source ID, and confidence score.

**`hp.answer_with_sources`**
```json
{
  "question": "What was the decision on the database migration?",
  "context_ids": ["doc-1", "doc-5"],
  "max_sources": 6
}
```
Returns a grounded answer with source citations (document ID + quote pairs).

**`hp.summarize_project`**
```json
{
  "project_id": "project-alpha",
  "style": "brief"
}
```
- `style` — `brief` or `detailed`

---

## Installation

### As Part of HomePilot

```bash
AGENTIC=1 make start
```

### Standalone

```bash
PYTHONPATH=/path/to/HomePilot uvicorn \
  agentic.integrations.mcp.knowledge_server:app \
  --host 0.0.0.0 --port 9102
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
knowledge/
├── pyproject.toml                # Project metadata
└── (server code in parent directory)
    └── knowledge_server.py       # Tool definitions and handlers
```

---

## Part of the HomePilot Ecosystem

This is one of the 5 core MCP tool servers that ship with HomePilot.

| Core Server | Port | Purpose |
| :--- | :--- | :--- |
| Personal Assistant | 9101 | Task management, day planning |
| **Knowledge** | 9102 | Document search, RAG queries |
| Decision Copilot | 9103 | Decision frameworks, risk assessment |
| Executive Briefing | 9104 | Daily/weekly digests, change summaries |
| Web Search | 9105 | Real-time web research |

---

<p align="center">
  <b>HomePilot</b> — Your AI. Your data. Your rules.<br>
  <a href="https://github.com/ruslanmv/HomePilot">GitHub</a> · <a href="../../../../docs/INTEGRATIONS.md">Integrations Guide</a>
</p>
