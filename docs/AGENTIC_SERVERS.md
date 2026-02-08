# Agentic Servers Architecture

## Overview

HomePilot ships with a suite of **MCP tool servers** and **A2A (Agent-to-Agent) agents** that start automatically alongside the main application. These servers provide the building blocks that AI agents use to search knowledge, make decisions, compose briefings, and research the web — all running locally with no external dependencies required.

---

## MCP Tool Servers

Each MCP server exposes tools via JSON-RPC 2.0, compatible with MCP Context Forge.

| Server | Port | Tools | Description |
| :--- | :--- | :--- | :--- |
| **Personal Assistant** | 9101 | `hp.personal.search`, `hp.personal.plan_day` | Everyday planning and personal knowledge search |
| **Knowledge** | 9102 | `hp.search_workspace`, `hp.get_document`, `hp.answer_with_sources`, `hp.summarize_project` | Workspace-aware document retrieval and Q&A |
| **Decision Copilot** | 9103 | `hp.decision.options`, `hp.decision.risk_assessment`, `hp.decision.recommend_next`, `hp.decision.plan_next_steps` | Structured decision-making with risk analysis |
| **Executive Briefing** | 9104 | `hp.brief.daily`, `hp.brief.weekly`, `hp.brief.what_changed_since`, `hp.brief.digest` | High-signal daily and weekly summaries |
| **Web Search** | 9105 | `hp.web.search`, `hp.web.fetch` | Web research via SearXNG (home) or Tavily (enterprise) |

## A2A Agents

A2A agents coordinate multi-step workflows by composing tool calls and applying safety policies.

| Agent | Port | Description |
| :--- | :--- | :--- |
| **Everyday Assistant** | 9201 | Friendly helper for summarization and planning. Read-only and advisory. |
| **Chief of Staff** | 9202 | Orchestrates: gather facts, structure options, produce briefings. Requires confirmation before acting. |

---

## How It Works

```
make start (AGENTIC=1)
    |
    +--> Backend (:8000) + Frontend (:3000) + ComfyUI (:8188)
    |
    +--> MCP Context Forge Gateway (:4444)
    |
    +--> scripts/agentic-start.sh
             |
             +--> Start 5 MCP servers (ports 9101-9105)
             +--> Start 2 A2A agents (ports 9201-9202)
             +--> Health-check all 7 services
             +--> Seed Forge (register gateways, agents, virtual servers)
```

After startup, the agent creation wizard in the UI can discover all registered tools and agents through the Forge catalog, letting users bind them to new agent projects.

---

## Web Search Provider Configuration

The Web Search MCP server (`hp.web.search`) supports two providers:

- **SearXNG** (default, home) — Self-hosted metasearch engine, no API key needed. Start SearXNG via `docker compose -f agentic/ops/compose/websearch.compose.yml up -d`.
- **Tavily** (enterprise) — Commercial web search API. Set `TAVILY_API_KEY` and `WEB_SEARCH_PROVIDER=tavily` in your environment.

Both providers expose the same stable tool contract, so agents work identically regardless of the backend.

---

## Suite Profiles

Suite manifests (`agentic/suite/default_home.yaml` and `agentic/suite/default_pro.yaml`) define which tool bundles and A2A agents appear in the agent wizard for each user profile. Both profiles include the Web Research bundle by default.
