"""MCP server: github — repos, PRs, issues, release notes.

Tools:
  github.repos.list(org?)
  github.issues.search(query, repo?)
  github.prs.list(repo, state?)
  github.pr.read(repo, pr_number)
  github.issue.create(repo, title, body)  [write-gated]
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from agentic.integrations.mcp._common.server import Json, ToolDef, create_mcp_app

WRITE_ENABLED = os.getenv("WRITE_ENABLED", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
GITHUB_ORG = os.getenv("GITHUB_ORG", "").strip()


def _text(text: str) -> Json:
    return {"content": [{"type": "text", "text": text}]}


def _write_gate(action: str) -> Json | None:
    if not WRITE_ENABLED:
        msg = f"Write disabled: '{action}' requires WRITE_ENABLED=true."
        if DRY_RUN:
            msg += " (DRY_RUN mode — no changes made)"
        return _text(msg)
    return None


async def github_repos_list(args: Json) -> Json:
    org = str(args.get("org", GITHUB_ORG)).strip()
    if not org:
        return _text("Please provide an 'org' or set GITHUB_ORG env var.")
    return _text(f"GitHub repos for org '{org}' — placeholder, token not yet configured.")


async def github_issues_search(args: Json) -> Json:
    query = str(args.get("query", "")).strip()
    repo = str(args.get("repo", "")).strip()
    if not query:
        return _text("Please provide a non-empty 'query'.")
    scope = f"in repo '{repo}'" if repo else "across all repos"
    return _text(f"GitHub issues search for '{query}' {scope} — placeholder.")


async def github_prs_list(args: Json) -> Json:
    repo = str(args.get("repo", "")).strip()
    state = str(args.get("state", "open")).strip()
    if not repo:
        return _text("Please provide a 'repo' (e.g. 'owner/repo').")
    return _text(f"GitHub PRs for '{repo}' (state={state}) — placeholder.")


async def github_pr_read(args: Json) -> Json:
    repo = str(args.get("repo", "")).strip()
    pr_number = args.get("pr_number")
    if not repo or pr_number is None:
        return _text("Please provide 'repo' and 'pr_number'.")
    return _text(f"GitHub PR #{pr_number} in '{repo}' — placeholder.")


async def github_issue_create(args: Json) -> Json:
    gate = _write_gate("github.issue.create")
    if gate:
        return gate
    repo = str(args.get("repo", "")).strip()
    title = str(args.get("title", "")).strip()
    body = str(args.get("body", "")).strip()
    if not repo or not title:
        return _text("Please provide 'repo' and 'title'.")
    return _text(f"Created issue in '{repo}': '{title}' — placeholder.")


TOOLS: List[ToolDef] = [
    ToolDef(
        name="hp.github.repos.list",
        description="List GitHub repositories for an organization.",
        input_schema={
            "type": "object",
            "properties": {
                "org": {"type": "string", "description": "GitHub organization name"},
            },
        },
        handler=github_repos_list,
    ),
    ToolDef(
        name="hp.github.issues.search",
        description="Search GitHub issues.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "repo": {"type": "string", "description": "Optional repo filter (owner/repo)"},
            },
            "required": ["query"],
        },
        handler=github_issues_search,
    ),
    ToolDef(
        name="hp.github.prs.list",
        description="List pull requests for a repository.",
        input_schema={
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"},
            },
            "required": ["repo"],
        },
        handler=github_prs_list,
    ),
    ToolDef(
        name="hp.github.pr.read",
        description="Read details of a pull request.",
        input_schema={
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "pr_number": {"type": "integer"},
            },
            "required": ["repo", "pr_number"],
        },
        handler=github_pr_read,
    ),
    ToolDef(
        name="hp.github.issue.create",
        description="Create a GitHub issue. Write-gated.",
        input_schema={
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["repo", "title", "body"],
        },
        handler=github_issue_create,
    ),
]

app = create_mcp_app(server_name="homepilot-github", tools=TOOLS)
