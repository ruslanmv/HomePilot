<p align="center">
  <img src="../../../../assets/blog/homepilot-compatible-badge.svg" alt="HomePilot MCP Compatible" width="280" />
</p>

# MCP GitHub

**Browse repos, search issues, list PRs, and create issues via the GitHub API.**

| | |
| :--- | :--- |
| **Server name** | `homepilot-github` |
| **Default port** | `9118` |
| **Persona** | Raven Okafor — *Dev Workflow Assistant* |
| **Role** | `assistant` |
| **Protocol** | JSON-RPC 2.0 (MCP v1) |

---

## What It Does

The GitHub MCP server connects your AI Persona to GitHub. It can list repositories for an organization, search issues, list pull requests, read PR details, and create issues — giving your Persona the ability to participate in your development workflow.

This enables: *"Raven, open a GitHub issue for the login bug I described yesterday."*

---

## Tools

| Tool | Description | Write-Gated |
| :--- | :--- | :---: |
| `hp.github.repos.list` | List GitHub repositories for an organization | No |
| `hp.github.issues.search` | Search GitHub issues | No |
| `hp.github.prs.list` | List pull requests for a repository | No |
| `hp.github.pr.read` | Read details of a pull request | No |
| `hp.github.issue.create` | Create a GitHub issue | Yes |

### Tool Details

**`hp.github.issues.search`**
```json
{
  "query": "login bug",
  "repo": "ruslanmv/HomePilot"
}
```
- `query` (string, required) — Search query
- `repo` (string, optional) — Filter to specific repo (`owner/repo`)

**`hp.github.issue.create`**
```json
{
  "repo": "ruslanmv/HomePilot",
  "title": "Login page returns 500 on mobile Safari",
  "body": "Steps to reproduce:\n1. Open login page on iOS Safari..."
}
```

**`hp.github.prs.list`**
```json
{
  "repo": "ruslanmv/HomePilot",
  "state": "open"
}
```
- `state` — `open`, `closed`, or `all`

---

## Installation

### Prerequisites

- Python 3.10 or later
- GitHub Personal Access Token (PAT) with `repo` scope

### Quick Start

```bash
cd agentic/integrations/mcp/github

cp .env.example .env
# Edit .env with your GitHub token and organization
make install
make run
```

The server starts on `http://0.0.0.0:9118` by default.

### GitHub Token Setup

1. Go to [github.com/settings/tokens](https://github.com/settings/tokens)
2. Create a fine-grained token with permissions: `Issues (Read & Write)`, `Pull Requests (Read)`, `Metadata (Read)`
3. Set `GITHUB_TOKEN` in `.env`
4. Optionally set `GITHUB_ORG` for the default organization

---

## Configuration

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `9118` | Server port |
| `WRITE_ENABLED` | `false` | Enable issue creation |
| `DRY_RUN` | `true` | Dry-run mode indicator |
| `GITHUB_ORG` | *(empty)* | Default GitHub organization |

---

## Testing

```bash
make test
```

---

## Project Structure

```
github/
├── app.py            # Server implementation with GitHub API integration
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
