<p align="center">
  <img src="../../../../assets/blog/homepilot-compatible-badge.svg" alt="HomePilot MCP Compatible" width="280" />
</p>

# MCP Decision Copilot

**Structured decision frameworks, risk assessment, and execution planning.**

| | |
| :--- | :--- |
| **Server name** | `homepilot-decision-copilot` |
| **Default port** | `9103` |
| **Protocol** | JSON-RPC 2.0 (MCP v1) |
| **Category** | Core Tool Server |

---

## What It Does

The Decision Copilot MCP server provides your AI Persona with structured decision-making frameworks. It generates options with pros, cons, and cost/risk ratings, assesses risks for proposals, recommends the best option based on configurable criteria, and turns decisions into actionable execution plans.

This is the server that powers: *"Should we build or buy? Give me the tradeoffs."*

---

## Tools

| Tool | Description |
| :--- | :--- |
| `hp.decision.options` | Generate decision options with tradeoffs |
| `hp.decision.risk_assessment` | Assess risks for a proposal |
| `hp.decision.recommend_next` | Recommend the best option from a list |
| `hp.decision.plan_next_steps` | Turn a decision into an execution plan |

### Tool Details

**`hp.decision.options`**
```json
{
  "goal": "Migrate from PostgreSQL to DynamoDB",
  "constraints": ["Must complete in Q2", "Budget under $50k"],
  "context": "Current system handles 10k req/s"
}
```
Returns 3 options (Low risk, Balanced, High impact) each with:
- Title, pros, cons, cost level, risk level, dependencies

**`hp.decision.risk_assessment`**
```json
{
  "proposal": "Switch to microservices architecture",
  "risk_tolerance": "medium"
}
```
- `risk_tolerance` — `low`, `medium`, or `high`

Returns risk score, identified risks, and mitigation strategies.

**`hp.decision.recommend_next`**
```json
{
  "options": [{"title": "Option A"}, {"title": "Option B (Balanced)"}],
  "decision_criteria": ["impact", "effort", "risk"]
}
```
Returns recommended option index, confidence score, and reasoning.

**`hp.decision.plan_next_steps`**
```json
{
  "decision": "Proceed with Option B",
  "time_horizon": "this_week"
}
```
- `time_horizon` — `today`, `this_week`, or `this_month`

Returns numbered steps with owner and due date.

---

## Installation

### As Part of HomePilot

```bash
AGENTIC=1 make start
```

### Standalone

```bash
PYTHONPATH=/path/to/HomePilot uvicorn \
  agentic.integrations.mcp.decision_copilot_server:app \
  --host 0.0.0.0 --port 9103
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
decision-copilot/
├── pyproject.toml                      # Project metadata
└── (server code in parent directory)
    └── decision_copilot_server.py      # Tool definitions and handlers
```

---

## Part of the HomePilot Ecosystem

This is one of the 5 core MCP tool servers that ship with HomePilot.

| Core Server | Port | Purpose |
| :--- | :--- | :--- |
| Personal Assistant | 9101 | Task management, day planning |
| Knowledge | 9102 | Document search, RAG queries |
| **Decision Copilot** | 9103 | Decision frameworks, risk assessment |
| Executive Briefing | 9104 | Daily/weekly digests, change summaries |
| Web Search | 9105 | Real-time web research |

---

<p align="center">
  <b>HomePilot</b> — Your AI. Your data. Your rules.<br>
  <a href="https://github.com/ruslanmv/HomePilot">GitHub</a> · <a href="../../../../docs/INTEGRATIONS.md">Integrations Guide</a>
</p>
