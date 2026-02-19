<p align="center">
  <img src="../../../../assets/blog/homepilot-compatible-badge.svg" alt="HomePilot MCP Compatible" width="280" />
</p>

# MCP Notion

**Search, read, and update Notion pages and databases.**

| | |
| :--- | :--- |
| **Server name** | `homepilot-notion` |
| **Default port** | `9119` |
| **Persona** | Elena Voss — *Knowledge Curator* |
| **Role** | `assistant` |
| **Protocol** | JSON-RPC 2.0 (MCP v1) |

---

## What It Does

The Notion MCP server connects your AI Persona to your Notion workspace. It can search across pages and databases, read page content by ID, and append new content to existing pages — giving your Persona access to your team's knowledge base.

This enables: *"Elena, find the onboarding checklist in Notion and add a new item."*

---

## Tools

| Tool | Description | Write-Gated |
| :--- | :--- | :---: |
| `hp.notion.search` | Search Notion pages and databases | No |
| `hp.notion.page.read` | Read a Notion page by ID | No |
| `hp.notion.page.append` | Append content to a Notion page | Yes |

### Tool Details

**`hp.notion.search`**
```json
{
  "query": "onboarding checklist",
  "limit": 10
}
```
- `query` (string, required) — Search query
- `limit` (integer, 1–100, default 20) — Maximum results

**`hp.notion.page.append`**
```json
{
  "page_id": "abc123-def456",
  "content": "- [ ] Complete security training"
}
```

---

## Installation

### Prerequisites

- Python 3.10 or later
- Notion integration token

### Quick Start

```bash
cd agentic/integrations/mcp/notion

cp .env.example .env
# Edit .env with your Notion integration token
make install
make run
```

The server starts on `http://0.0.0.0:9119` by default.

### Notion Integration Setup

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Create a new integration
3. Copy the Internal Integration Token
4. Set `NOTION_TOKEN` in `.env`
5. Share the pages/databases you want accessible with the integration

---

## Configuration

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `9119` | Server port |
| `WRITE_ENABLED` | `false` | Enable content appending |
| `DRY_RUN` | `true` | Dry-run mode indicator |

---

## Testing

```bash
make test
```

---

## Project Structure

```
notion/
├── app.py            # Server implementation with Notion API integration
├── pyproject.toml    # Dependencies
├── Makefile          # Install, test, run, clean, lint targets
├── .env.example      # Configuration template
├── __init__.py
└── tests/            # Test suite
```

---

## Part of the HomePilot Ecosystem

This server is one of 17 MCP tool servers in the HomePilot platform. It connects through the **Context Forge** gateway (port 4444).

---

<p align="center">
  <b>HomePilot</b> — Your AI. Your data. Your rules.<br>
  <a href="https://github.com/ruslanmv/HomePilot">GitHub</a> · <a href="../../../../docs/INTEGRATIONS.md">Integrations Guide</a>
</p>
