<p align="center">
  <img src="../../../../assets/blog/homepilot-compatible-badge.svg" alt="HomePilot MCP Compatible" width="280" />
</p>

# MCP Shell Safe

**Restricted local command execution with an explicit allowlist.**

| | |
| :--- | :--- |
| **Server name** | `homepilot-shell-safe` |
| **Default port** | `9113` |
| **Persona** | Soren Lindqvist — *Automation Operator* |
| **Role** | `assistant` |
| **Protocol** | JSON-RPC 2.0 (MCP v1) |

---

## What It Does

The Shell Safe MCP server lets your AI Persona execute a curated set of shell commands on the host machine. Only commands from the configurable allowlist can run. Read-only commands (`ls`, `cat`, `grep`, etc.) execute freely; commands that modify state (`python3`, `pip`, `git`, `make`, `npm`) require write permission.

Network commands (`curl`, `wget`, `ssh`, etc.) are blocked by default and require explicit opt-in.

---

## Tools

| Tool | Description | Write-Gated |
| :--- | :--- | :---: |
| `hp.shell.allowed` | List the allowlisted commands this server can execute | No |
| `hp.shell.run` | Execute a command from the allowlist | Conditional |

### Default Allowlist

```
ls, cat, head, tail, wc, grep, find, echo, date, whoami,
pwd, df, du, uname, python3, pip, git, make, npm
```

Read-only commands: `ls`, `cat`, `head`, `tail`, `wc`, `grep`, `find`, `echo`, `date`, `whoami`, `pwd`, `df`, `du`, `uname` — these run without write gating.

All other commands require `WRITE_ENABLED=true`.

### Tool Details

**`hp.shell.run`**
```json
{
  "command": "ls",
  "args": ["-la", "/home/user/project"],
  "cwd": "/home/user",
  "timeout": 10
}
```
- `command` (string, required) — Command name (must be in allowlist)
- `args` (array of strings, optional) — Command arguments
- `cwd` (string, optional) — Working directory (defaults to `SAFE_CWD`)
- `timeout` (integer, optional) — Timeout in seconds (capped at `EXEC_TIMEOUT`)

---

## Installation

### Quick Start

```bash
cd agentic/integrations/mcp/shell_safe

cp .env.example .env
make install
make run
```

The server starts on `http://0.0.0.0:9113` by default.

---

## Configuration

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `9113` | Server port |
| `WRITE_ENABLED` | `false` | Enable non-read-only command execution |
| `DRY_RUN` | `true` | Dry-run mode indicator |
| `EXEC_TIMEOUT` | `30` | Maximum execution time per command (seconds) |
| `MAX_OUTPUT_BYTES` | `1048576` | Maximum output size (1 MB) |
| `SAFE_CWD` | `~` | Default working directory |
| `ALLOWED_COMMANDS` | *(see above)* | Comma-separated list of allowed commands |
| `ALLOW_NETWORK_COMMANDS` | `false` | Enable network commands (curl, wget, ssh, etc.) |

### Security Model

1. **Allowlist enforcement**: Only commands in `ALLOWED_COMMANDS` can execute. All others are rejected.
2. **Read/Write separation**: Read-only commands run freely. Write-capable commands require `WRITE_ENABLED=true`.
3. **Network isolation**: Network commands are blocked unless `ALLOW_NETWORK_COMMANDS=true`.
4. **Timeout protection**: Commands are killed after `EXEC_TIMEOUT` seconds.
5. **Output limits**: Output is truncated at `MAX_OUTPUT_BYTES`.

---

## Testing

```bash
make test
```

---

## Project Structure

```
shell_safe/
├── app.py            # Server implementation with allowlist enforcement
├── pyproject.toml    # Dependencies and project metadata
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
