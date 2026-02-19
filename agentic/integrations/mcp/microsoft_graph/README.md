<p align="center">
  <img src="../../../../assets/blog/homepilot-compatible-badge.svg" alt="HomePilot MCP Compatible" width="280" />
</p>

# MCP Microsoft Graph

**Outlook mail and calendar access via the Microsoft Graph API.**

| | |
| :--- | :--- |
| **Server name** | `homepilot-microsoft-graph` |
| **Default port** | `9116` |
| **Persona** | Diana Brooks — *Office Navigator* |
| **Role** | `secretary` |
| **Protocol** | JSON-RPC 2.0 (MCP v1) |

---

## What It Does

The Microsoft Graph MCP server gives your AI Persona access to Outlook mail and calendar through Microsoft's Graph API. It provides a unified interface for searching and reading mail, creating and sending drafts, listing calendar events, and reading event details.

This is the enterprise connector: if your organization uses Microsoft 365, this server lets your Persona operate within that ecosystem.

---

## Tools

### Mail

| Tool | Description | Write-Gated |
| :--- | :--- | :---: |
| `hp.graph.mail.search` | Search Outlook mail | No |
| `hp.graph.mail.read` | Read an Outlook message by ID | No |
| `hp.graph.mail.draft` | Create an Outlook mail draft | Yes |
| `hp.graph.mail.send` | Send an Outlook draft | Yes |

### Calendar

| Tool | Description | Write-Gated |
| :--- | :--- | :---: |
| `hp.graph.calendar.list_events` | List Outlook calendar events in a time range | No |
| `hp.graph.calendar.read_event` | Read an Outlook calendar event by ID | No |

### Tool Details

**`hp.graph.mail.draft`**
```json
{
  "to": "colleague@company.com",
  "subject": "Q1 Report Review",
  "body": "Please review the attached report...",
  "thread_id": "AAMk..."
}
```

**`hp.graph.calendar.list_events`**
```json
{
  "time_min": "2026-02-18T00:00:00Z",
  "time_max": "2026-02-25T00:00:00Z"
}
```

---

## Installation

### Prerequisites

- Python 3.10 or later
- Azure AD app registration with Microsoft Graph permissions
- OAuth 2.0 credentials (client ID, client secret, tenant ID)

### Quick Start

```bash
cd agentic/integrations/mcp/microsoft_graph

cp .env.example .env
# Edit .env with your Azure AD credentials
make install
make run
```

The server starts on `http://0.0.0.0:9116` by default.

### Azure AD Setup

1. Go to the [Azure Portal](https://portal.azure.com/) > Azure Active Directory > App registrations
2. Register a new application
3. Add API permissions: `Mail.Read`, `Mail.Send`, `Calendars.Read`, `Calendars.ReadWrite`
4. Create a client secret
5. Set `MS_GRAPH_CLIENT_ID`, `MS_GRAPH_CLIENT_SECRET`, and `MS_GRAPH_TENANT_ID` in `.env`

---

## Configuration

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `9116` | Server port |
| `WRITE_ENABLED` | `false` | Enable draft creation and sending |
| `DRY_RUN` | `true` | Dry-run mode indicator |

---

## Testing

```bash
make test
```

---

## Project Structure

```
microsoft_graph/
├── app.py            # Server implementation (mail + calendar tools)
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
