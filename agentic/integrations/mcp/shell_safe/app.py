"""MCP server: shell-safe — restricted local command execution.

Tools:
  shell.allowed()
  shell.run(command, args=[], cwd?, timeout?)  [write-gated by policy]
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from agentic.integrations.mcp._common.server import Json, ToolDef, create_mcp_app

WRITE_ENABLED = os.getenv("WRITE_ENABLED", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
EXEC_TIMEOUT = int(os.getenv("EXEC_TIMEOUT", "30"))
MAX_OUTPUT_BYTES = int(os.getenv("MAX_OUTPUT_BYTES", "1048576"))
SAFE_CWD = os.getenv("SAFE_CWD", os.path.expanduser("~"))
ALLOW_NETWORK_COMMANDS = os.getenv("ALLOW_NETWORK_COMMANDS", "false").lower() == "true"

_DEFAULT_ALLOWED = "ls,cat,head,tail,wc,grep,find,echo,date,whoami,pwd,df,du,uname,python3,pip,git,make,npm"
ALLOWED_COMMANDS = [c.strip() for c in os.getenv("ALLOWED_COMMANDS", _DEFAULT_ALLOWED).split(",") if c.strip()]

_NETWORK_COMMANDS = {"curl", "wget", "ssh", "scp", "rsync", "nc", "ncat", "nmap", "ping", "traceroute"}


def _text(text: str) -> Json:
    return {"content": [{"type": "text", "text": text}]}


def _write_gate(action: str) -> Json | None:
    if not WRITE_ENABLED:
        msg = f"Write disabled: '{action}' requires WRITE_ENABLED=true."
        if DRY_RUN:
            msg += " (DRY_RUN mode — no changes made)"
        return _text(msg)
    return None


async def shell_allowed(args: Json) -> Json:
    return {
        "allowed_commands": ALLOWED_COMMANDS,
        "network_commands_enabled": ALLOW_NETWORK_COMMANDS,
        "exec_timeout": EXEC_TIMEOUT,
        "safe_cwd": SAFE_CWD,
    }


async def shell_run(args: Json) -> Json:
    command = str(args.get("command", "")).strip()
    cmd_args = args.get("args") or []
    if isinstance(cmd_args, str):
        cmd_args = cmd_args.split()
    cwd = str(args.get("cwd", "")).strip() or SAFE_CWD
    timeout = min(int(args.get("timeout", EXEC_TIMEOUT) or EXEC_TIMEOUT), EXEC_TIMEOUT)

    if not command:
        return _text("Please provide a 'command'.")

    if command not in ALLOWED_COMMANDS:
        return _text(f"Command '{command}' is not in the allowlist. Use shell.allowed() to see available commands.")

    if not ALLOW_NETWORK_COMMANDS and command in _NETWORK_COMMANDS:
        return _text(f"Network command '{command}' is disabled. Set ALLOW_NETWORK_COMMANDS=true to enable.")

    # Write-gate for commands that modify (heuristic: anything not read-only)
    _READ_ONLY = {"ls", "cat", "head", "tail", "wc", "grep", "find", "echo", "date", "whoami", "pwd", "df", "du", "uname"}
    if command not in _READ_ONLY:
        gate = _write_gate(f"shell.run({command})")
        if gate:
            return gate

    # Placeholder — production would use asyncio.create_subprocess_exec
    full_cmd = " ".join([command] + [str(a) for a in cmd_args])
    return _text(f"Would execute: `{full_cmd}` in '{cwd}' (timeout={timeout}s). [placeholder — not yet wired to subprocess]")


TOOLS: List[ToolDef] = [
    ToolDef(
        name="hp.shell.allowed",
        description="List the allowlisted commands this server can execute.",
        input_schema={
            "type": "object",
            "properties": {},
        },
        handler=shell_allowed,
    ),
    ToolDef(
        name="hp.shell.run",
        description="Execute a command from the allowlist. Write-gated for non-read-only commands.",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command name (must be in allowlist)"},
                "args": {"type": "array", "items": {"type": "string"}, "default": []},
                "cwd": {"type": "string", "description": "Working directory (optional)"},
                "timeout": {"type": "integer", "description": "Timeout in seconds"},
            },
            "required": ["command"],
        },
        handler=shell_run,
    ),
]

app = create_mcp_app(server_name="homepilot-shell-safe", tools=TOOLS)
