<p align="center">
  <img src="../../../../assets/blog/homepilot-compatible-badge.svg" alt="HomePilot MCP Compatible" width="280" />
</p>

# MCP Local Projects

**Safe, sandboxed access to local project and workspace files.**

| | |
| :--- | :--- |
| **Server name** | `homepilot-local-projects` |
| **Default port** | `9111` |
| **Persona** | Felix Navarro — *Project Navigator* |
| **Role** | `assistant` |
| **Protocol** | JSON-RPC 2.0 (MCP v1) |

---

## What It Does

The Local Projects MCP server lets your AI Persona browse, read, search, and optionally write files on your local filesystem — within strictly defined boundaries. It enforces an allowlist of root directories and blocks access to sensitive paths (`.ssh`, `.gnupg`, `.aws`, `.env`, `.git/config`, `credentials.json`).

This is the server that turns a Persona into a code-aware assistant: it can read project files, search across source code, preview diffs, and make controlled edits when you grant write permission.

---

## Tools

| Tool | Description | Write-Gated |
| :--- | :--- | :---: |
| `hp.projects.list` | List files and directories in a project root | No |
| `hp.projects.read_file` | Read the contents of a file | No |
| `hp.projects.search_text` | Search for text across project files | No |
| `hp.projects.write_file` | Write content to a file | Yes |
| `hp.projects.diff` | Preview a diff between existing file and proposed content | No |

### Tool Details

**`hp.projects.list`**
```json
{
  "root_path": "/home/user/my-project"
}
```
Returns up to 200 entries (name, type, size). Hidden files (starting with `.`) are excluded.

**`hp.projects.read_file`**
```json
{
  "path": "/home/user/my-project/src/main.py"
}
```
Reads up to 100,000 characters. Returns path, content, and file size.

**`hp.projects.diff`**
```json
{
  "path": "/home/user/my-project/src/main.py",
  "proposed_content": "# Updated content here..."
}
```
Safe, read-only preview of what would change.

---

## Installation

### Prerequisites

- Python 3.10 or later
- [uv](https://github.com/astral-sh/uv) package manager (recommended) or pip

### Quick Start

```bash
cd agentic/integrations/mcp/local_projects

# Copy environment configuration
cp .env.example .env

# Install dependencies into isolated virtual environment
make install

# Run the server
make run
```

The server starts on `http://0.0.0.0:9111` by default.

---

## Configuration

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `9111` | Server port |
| `HOST` | `0.0.0.0` | Bind address |
| `WRITE_ENABLED` | `false` | Enable file write operations |
| `DRY_RUN` | `true` | Indicate dry-run mode in responses when writes are disabled |
| `ALLOWED_ROOTS` | *(empty)* | Comma-separated list of allowed root directories |

### Security Model

- **Path Allowlist**: Only paths within `ALLOWED_ROOTS` directories are accessible. If `ALLOWED_ROOTS` is empty, all paths are allowed (suitable for development).
- **Blocked Patterns**: `.ssh`, `.gnupg`, `.aws`, `.env`, `.git/config`, and `credentials.json` are always blocked regardless of root configuration.
- **Write Gating**: File writes require `WRITE_ENABLED=true`.

---

## Testing

```bash
make test
```

---

## API Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/health` | GET | Health check |
| `/rpc` | POST | JSON-RPC 2.0 endpoint for MCP protocol |

---

## Project Structure

```
local_projects/
├── app.py            # Server implementation and tool definitions
├── pyproject.toml    # Dependencies and project metadata
├── Makefile          # Install, test, run, clean, lint targets
├── .env.example      # Configuration template
├── __init__.py
└── tests/            # Test suite
```

---

## Part of the HomePilot Ecosystem

This server is one of 17 MCP tool servers in the HomePilot platform. It connects through the **Context Forge** gateway (port 4444) and can be used by any HomePilot Persona in linked mode.

---

<p align="center">
  <b>HomePilot</b> — Your AI. Your data. Your rules.<br>
  <a href="https://github.com/ruslanmv/HomePilot">GitHub</a> · <a href="../../../../docs/INTEGRATIONS.md">Integrations Guide</a>
</p>
