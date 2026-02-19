<p align="center">
  <img src="../../../../assets/blog/homepilot-compatible-badge.svg" alt="HomePilot MCP Compatible" width="280" />
</p>

# A2A Everyday Assistant

**A friendly, read-only advisory agent that summarizes and plans.**

| | |
| :--- | :--- |
| **Agent name** | `everyday-assistant` |
| **Default port** | `9201` |
| **Protocol** | A2A v1 (Agent-to-Agent) |
| **Safety** | Read-only + Advisory (no side effects) |

---

## What It Does

The Everyday Assistant is a lightweight A2A (Agent-to-Agent) agent that provides friendly, actionable advice. It does not perform actions or modify state — it only reads, summarizes, and suggests next steps.

It supports three persona modes that adjust its communication style:
- **Friendly** (default) — Warm, encouraging tone: *"Sure — here is a simple next step..."*
- **Neutral** — Factual, concise: *"Okay. Here is a simple next step..."*
- **Focused** — Direct, minimal: *"Got it. Here is a simple next step..."*

---

## How It Works

The Everyday Assistant receives messages through the A2A protocol and returns structured responses. Every response includes:

- **Agent ID**: `everyday-assistant`
- **Text**: A friendly summary with a suggested next step
- **Policy**: `can_act: false`, `needs_confirmation: true`

The agent never takes autonomous action. It always defers to the user for confirmation.

### Example

**Input:**
```json
{
  "text": "I need to prepare for tomorrow's presentation",
  "meta": {"persona": "friendly"}
}
```

**Output:**
```json
{
  "agent": "everyday-assistant",
  "text": "Sure — here is a simple next step: write down the 1–3 outcomes you want today.\n\nYou said: I need to prepare for tomorrow's presentation",
  "policy": {
    "can_act": false,
    "needs_confirmation": true
  }
}
```

---

## Installation

### As Part of HomePilot

```bash
AGENTIC=1 make start
```

### Standalone

```bash
PYTHONPATH=/path/to/HomePilot uvicorn \
  agentic.integrations.a2a.everyday_assistant_agent:app \
  --host 0.0.0.0 --port 9201
```

---

## API Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/health` | GET | Health check |
| `/rpc` | POST | A2A message endpoint |

---

## Configuration

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `9201` | Server port |

No additional configuration required. This agent has no external dependencies.

---

## Project Structure

```
everyday-assistant/
├── pyproject.toml                         # Project metadata
└── (agent code in parent directory)
    └── everyday_assistant_agent.py        # Message handler and agent definition
```

---

## Part of the HomePilot Ecosystem

This is one of 2 A2A agents that ship with HomePilot. A2A agents coordinate with each other and with MCP tool servers through the **Context Forge** gateway.

| Agent | Port | Purpose |
| :--- | :--- | :--- |
| **Everyday Assistant** | 9201 | Friendly summaries, simple planning |
| Chief of Staff | 9202 | Orchestration, decision support, briefings |

---

<p align="center">
  <b>HomePilot</b> — Your AI. Your data. Your rules.<br>
  <a href="https://github.com/ruslanmv/HomePilot">GitHub</a> · <a href="../../../../docs/INTEGRATIONS.md">Integrations Guide</a>
</p>
