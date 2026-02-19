<p align="center">
  <img src="../../../../assets/blog/homepilot-compatible-badge.svg" alt="HomePilot MCP Compatible" width="280" />
</p>

# MCP Gmail

**Search, read, draft, and send email through the Gmail API.**

| | |
| :--- | :--- |
| **Server name** | `homepilot-gmail` |
| **Default port** | `9114` |
| **Persona** | Priya Sharma — *Email Manager* |
| **Role** | `secretary` |
| **Protocol** | JSON-RPC 2.0 (MCP v1) |

---

## What It Does

The Gmail MCP server connects your AI Persona to your Gmail account via the Google Gmail API. Your Persona can search messages, read specific emails, create drafts, and send them — all gated by configurable safety controls.

This is the server that enables natural-language email management: *"Priya, find the client email from yesterday and draft a reply."*

---

## Tools

| Tool | Description | Write-Gated |
| :--- | :--- | :---: |
| `hp.gmail.search` | Search Gmail messages using Gmail query syntax | No |
| `hp.gmail.read` | Read a Gmail message by ID | No |
| `hp.gmail.draft` | Create a Gmail draft | Yes |
| `hp.gmail.send` | Send a Gmail draft | Yes |

### Tool Details

**`hp.gmail.search`**
```json
{
  "query": "from:client@example.com subject:proposal",
  "limit": 10
}
```
Uses standard Gmail search syntax.

**`hp.gmail.draft`**
```json
{
  "to": "client@example.com",
  "subject": "Re: Proposal Review",
  "body": "Thank you for the proposal...",
  "thread_id": "abc123"
}
```
- `to` (string, required) — Recipient email
- `subject` (string, required) — Email subject
- `body` (string, required) — Email body
- `thread_id` (string, optional) — Thread ID for replies

---

## Installation

### Prerequisites

- Python 3.10 or later
- Google Cloud project with Gmail API enabled
- OAuth 2.0 credentials (`credentials.json`)

### Quick Start

```bash
cd agentic/integrations/mcp/gmail

cp .env.example .env
# Edit .env with your OAuth credentials path
make install
make run
```

### Google OAuth Setup

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable the **Gmail API**
3. Create OAuth 2.0 credentials (Desktop application)
4. Download `credentials.json` and place it in the server directory
5. On first run, complete the OAuth flow in your browser

---

## Configuration

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `9114` | Server port |
| `WRITE_ENABLED` | `false` | Enable draft creation and sending |
| `DRY_RUN` | `true` | Dry-run mode indicator |
| `CONFIRM_SEND` | `true` | Require explicit confirmation before sending |

### Safety Model

- **Read operations** (`search`, `read`) work without write permission
- **Draft creation** requires `WRITE_ENABLED=true`
- **Sending** requires both `WRITE_ENABLED=true` and (optionally) `CONFIRM_SEND=false` for automatic sending

---

## Dependencies

```
google-auth >= 2.0
google-auth-oauthlib >= 1.0
google-api-python-client >= 2.0
```

---

## Testing

```bash
make test
```

---

## Project Structure

```
gmail/
├── app.py            # Server implementation with Gmail API integration
├── pyproject.toml    # Dependencies (includes google-auth, google-api-python-client)
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
