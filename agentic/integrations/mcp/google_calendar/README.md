<p align="center">
  <img src="../../../../assets/blog/homepilot-compatible-badge.svg" alt="HomePilot MCP Compatible" width="280" />
</p>

# MCP Google Calendar

**Read events, search meetings, and create calendar entries via the Google Calendar API.**

| | |
| :--- | :--- |
| **Server name** | `homepilot-google-calendar` |
| **Default port** | `9115` |
| **Persona** | Luca Moretti — *Calendar Strategist* |
| **Role** | `secretary` |
| **Protocol** | JSON-RPC 2.0 (MCP v1) |

---

## What It Does

The Google Calendar MCP server connects your AI Persona to Google Calendar. It can list events in a time range, search for specific meetings, read event details, and create new events — all with standard MCP write gating.

This is what makes *"Luca, block two hours tomorrow for the proposal review"* actually work.

---

## Tools

| Tool | Description | Write-Gated |
| :--- | :--- | :---: |
| `hp.gcal.list_events` | List calendar events in a time range | No |
| `hp.gcal.search` | Search calendar events by query | No |
| `hp.gcal.read_event` | Read details of a calendar event by ID | No |
| `hp.gcal.create_event` | Create a new calendar event | Yes |

### Tool Details

**`hp.gcal.list_events`**
```json
{
  "time_min": "2026-02-18T00:00:00Z",
  "time_max": "2026-02-19T00:00:00Z"
}
```
Both timestamps use ISO 8601 format.

**`hp.gcal.create_event`**
```json
{
  "title": "Proposal Review",
  "start": "2026-02-19T14:00:00Z",
  "end": "2026-02-19T16:00:00Z",
  "attendees": ["alice@example.com", "bob@example.com"],
  "location": "Conference Room B"
}
```

---

## Installation

### Prerequisites

- Python 3.10 or later
- Google Cloud project with Calendar API enabled
- OAuth 2.0 credentials

### Quick Start

```bash
cd agentic/integrations/mcp/google_calendar

cp .env.example .env
make install
make run
```

The server starts on `http://0.0.0.0:9115` by default.

---

## Configuration

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `9115` | Server port |
| `WRITE_ENABLED` | `false` | Enable event creation |
| `DRY_RUN` | `true` | Dry-run mode indicator |

---

## Testing

```bash
make test
```

---

## Project Structure

```
google_calendar/
├── app.py            # Server implementation with Calendar API integration
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
