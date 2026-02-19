<p align="center">
  <img src="../../../../assets/blog/homepilot-compatible-badge.svg" alt="HomePilot MCP Compatible" width="280" />
</p>

# A2A Chief of Staff

**Orchestrator agent: gathers facts, structures options, produces briefings.**

| | |
| :--- | :--- |
| **Agent name** | `chief-of-staff` |
| **Default port** | `9202` |
| **Protocol** | A2A v1 (Agent-to-Agent) |
| **Safety** | No external side effects, confirmation required |

---

## What It Does

The Chief of Staff is an orchestrator A2A (Agent-to-Agent) agent that takes a request, gathers relevant workspace facts (via MCP tool servers), and produces a structured briefing with clearly separated sections: what it knows, what it assumes, what the options are, and what it recommends.

It is designed for executive-level decision support: you ask a question, and the Chief of Staff does the research, structures the answer, and asks the right follow-up question.

---

## How It Works

1. **Receive message** from a Persona or another agent
2. **Enrich** by querying workspace knowledge via Context Forge (`hp.search_workspace`)
3. **Structure response** into 5 sections:
   - **What I know** — Facts from workspace search
   - **What I assume** — Stated assumptions
   - **Options** — 3 ranked options (quick win, safe plan, deep dive)
   - **Recommendation** — Top recommendation with confidence score
   - **Question for you** — Clarifying question to refine the answer

### Supported Modes

| Mode | Behavior |
| :--- | :--- |
| `auto` (default) | Enriches with workspace search |
| `knowledge` | Focuses on workspace knowledge retrieval |
| `decision` | Focuses on decision frameworks |

### Example

**Input:**
```json
{
  "text": "Should we migrate the analytics service to Kafka?",
  "meta": {"mode": "auto"}
}
```

**Output:**
```json
{
  "agent": "chief-of-staff",
  "text": "**What I know**\n- Workspace search hints: ...\n\n**What I assume**\n- You want a practical next step...\n\n**Options**\n1) Quick win: define success criteria...\n2) Safe plan: list risks + mitigations...\n3) Deep dive: gather sources...\n\n**Recommendation (with confidence)**\n- Start with option 1 today. (confidence: 0.65)\n\n**Question for you**\n- What's the deadline and what does 'good' look like?",
  "policy": {"can_act": false, "needs_confirmation": true}
}
```

---

## Tool Integration

The Chief of Staff can invoke MCP tools through Context Forge to enrich its responses:

```
Chief of Staff → Context Forge (:4444) → hp.search_workspace → Knowledge Server (:9102)
```

This is a best-effort enrichment: if Context Forge or the Knowledge server is unavailable, the agent gracefully falls back to its default response structure.

---

## Installation

### As Part of HomePilot

```bash
AGENTIC=1 make start
```

### Standalone

```bash
PYTHONPATH=/path/to/HomePilot uvicorn \
  agentic.integrations.a2a.chief_of_staff_agent:app \
  --host 0.0.0.0 --port 9202
```

---

## Configuration

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `9202` | Server port |
| `MCPGATEWAY_URL` | `http://localhost:4444` | Context Forge gateway URL |
| `BASIC_AUTH_USER` | `admin` | Gateway authentication user |
| `BASIC_AUTH_PASSWORD` | `changeme` | Gateway authentication password |

---

## API Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/health` | GET | Health check |
| `/rpc` | POST | A2A message endpoint |

---

## Project Structure

```
chief-of-staff/
├── pyproject.toml                       # Project metadata
└── (agent code in parent directory)
    └── chief_of_staff_agent.py          # Message handler with tool integration
```

---

## Part of the HomePilot Ecosystem

This is one of 2 A2A agents that ship with HomePilot.

| Agent | Port | Purpose |
| :--- | :--- | :--- |
| Everyday Assistant | 9201 | Friendly summaries, simple planning |
| **Chief of Staff** | 9202 | Orchestration, decision support, briefings |

---

<p align="center">
  <b>HomePilot</b> — Your AI. Your data. Your rules.<br>
  <a href="https://github.com/ruslanmv/HomePilot">GitHub</a> · <a href="../../../../docs/INTEGRATIONS.md">Integrations Guide</a>
</p>
