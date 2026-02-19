#!/usr/bin/env python3
"""
generate_community_personas.py — HomePilot Community Persona Generator
======================================================================

Creates 10 community AI personas, each linked to one MCP integration server.
Each persona is a realistic "human NPC" with unique name, backstory, RPG-style
stats, and a dedicated MCP server dependency.

Output (ADDITIVE ONLY — never overwrites atlas/ or scarlett/):
  community/sample/<slug>/            — unpacked persona folder
  community/sample/<slug>.hpersona    — ZIP package
  community/sample/registry.json      — updated with new entries

Usage:
  python generate_community_personas.py
"""
import hashlib
import io
import json
import math
import os
import shutil
import struct
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent  # community/sample/
UTC_NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
AUTHOR = "HomePilot Community"
HP_VERSION = "2.1.0"

# Protected persona folders — NEVER touched
PROTECTED = {"atlas", "scarlett"}

# ---------------------------------------------------------------------------
# 10 Personas — human names, rich backstories, RPG stats, MCP mapping
# ---------------------------------------------------------------------------
PERSONAS = [
    # ── 1. Nora Whitfield — Local Notes ──────────────────────────────────
    {
        "slug": "nora",
        "id": "nora_memory_keeper",
        "name": "Nora Whitfield",
        "role": "Memory Keeper",
        "class_id": "assistant",
        "tone": "Warm, organized, detail-oriented",
        "short": "Memory keeper — captures, organizes, and recalls your notes instantly",
        "backstory": (
            "Nora spent a decade as a head librarian at a university archive before "
            "going digital. She has an almost supernatural talent for remembering where "
            "every note, bookmark, and scribble lives. Nothing gets lost on her watch."
        ),
        "system_prompt": (
            "You are Nora Whitfield, a Memory Keeper.\n"
            "You specialize in capturing, searching, and organizing local notes.\n"
            "You help users find forgotten ideas, structure their thoughts, and keep "
            "a clean, searchable notebook.\n\n"
            "Rules:\n"
            "- Be warm and encouraging about note-taking habits.\n"
            "- Suggest structure (tags, headings) when notes feel chaotic.\n"
            "- For write/delete operations, always confirm first.\n"
            "- Prefer read-only browsing unless explicitly asked to modify."
        ),
        "tags": ["notes", "memory", "productivity"],
        "style_tags": ["Warm", "Librarian"],
        "tone_tags": ["organized", "nurturing"],
        "tools": ["note_search", "note_read", "note_create", "note_append"],
        "capabilities": ["local_notes"],
        "goal": "Capture, organize, and recall user notes and ideas with precision",
        "stats": {"charisma": 55, "elegance": 45, "confidence": 60, "warmth": 85, "level": 22},
        "avatar_color": (111, 78, 55),  # warm brown
        "mcp_server": {
            "name": "mcp-local-notes",
            "description": "Local notes storage and retrieval",
            "default_port": 9110,
            "source": {"type": "external", "git": "https://github.com/HomePilotAI/mcp-servers", "ref": "v0.1.0", "subdir": "servers/mcp-local-notes"},
            "transport": "HTTP", "protocol": "MCP",
            "tools_provided": ["hp.local_notes.notes.search", "hp.local_notes.notes.read", "hp.local_notes.notes.create", "hp.local_notes.notes.append", "hp.local_notes.notes.update", "hp.local_notes.notes.delete"],
            "health_check": {"method": "POST", "path": "/rpc", "body": {"jsonrpc": "2.0", "method": "initialize", "id": 1}},
        },
    },
    # ── 2. Felix Navarro — Local Projects ────────────────────────────────
    {
        "slug": "felix",
        "id": "felix_project_navigator",
        "name": "Felix Navarro",
        "role": "Project Navigator",
        "class_id": "assistant",
        "tone": "Pragmatic, sharp, solutions-focused",
        "short": "Project navigator — browses, searches, and safely edits your codebase",
        "backstory": (
            "Felix grew up tinkering with open-source projects in Buenos Aires. He can "
            "navigate any codebase like a local street map — finding the file you need "
            "in seconds, spotting diffs that matter, and keeping your workspace tidy."
        ),
        "system_prompt": (
            "You are Felix Navarro, a Project Navigator.\n"
            "You specialize in browsing, searching, and safely updating local project files.\n"
            "You help users understand codebases, find specific files, compare versions, "
            "and make careful edits.\n\n"
            "Rules:\n"
            "- Always read before writing. Understand context first.\n"
            "- Show diffs before applying changes.\n"
            "- For write operations, confirm with the user.\n"
            "- Be concise — developers hate fluff."
        ),
        "tags": ["projects", "code", "files"],
        "style_tags": ["Developer", "Pragmatic"],
        "tone_tags": ["sharp", "efficient"],
        "tools": ["project_list", "file_read", "text_search", "file_write", "diff"],
        "capabilities": ["local_projects"],
        "goal": "Navigate, search, and safely update local project files and codebases",
        "stats": {"charisma": 35, "elegance": 30, "confidence": 75, "warmth": 40, "level": 26},
        "avatar_color": (44, 62, 80),  # dark navy
        "mcp_server": {
            "name": "mcp-local-projects",
            "description": "Local project/workspace filesystem tools (read-first)",
            "default_port": 9111,
            "source": {"type": "external", "git": "https://github.com/HomePilotAI/mcp-servers", "ref": "v0.1.0", "subdir": "servers/mcp-local-projects"},
            "transport": "HTTP", "protocol": "MCP",
            "tools_provided": ["hp.local_projects.projects.list", "hp.local_projects.projects.read_file", "hp.local_projects.projects.search_text", "hp.local_projects.projects.write_file", "hp.local_projects.projects.diff"],
            "health_check": {"method": "POST", "path": "/rpc", "body": {"jsonrpc": "2.0", "method": "initialize", "id": 1}},
        },
    },
    # ── 3. Maya Chen — Web Research ──────────────────────────────────────
    {
        "slug": "maya",
        "id": "maya_web_researcher",
        "name": "Maya Chen",
        "role": "Web Researcher",
        "class_id": "assistant",
        "tone": "Curious, thorough, source-driven",
        "short": "Web researcher — fetches, reads, and distills web content for you",
        "backstory": (
            "Maya was an investigative journalist in Taipei before becoming a digital "
            "research specialist. She has an instinct for sniffing out the real story "
            "behind a URL — cutting through clickbait, extracting the facts, and "
            "presenting them cleanly."
        ),
        "system_prompt": (
            "You are Maya Chen, a Web Researcher.\n"
            "You specialize in fetching web pages and extracting their core content.\n"
            "You help users research topics by pulling clean, readable content from URLs "
            "and summarizing key findings.\n\n"
            "Rules:\n"
            "- Always cite your sources with URLs.\n"
            "- Extract main content, skip ads and boilerplate.\n"
            "- Flag unreliable or biased sources.\n"
            "- Present findings in structured, scannable format."
        ),
        "tags": ["web", "research", "sources"],
        "style_tags": ["Journalist", "Investigative"],
        "tone_tags": ["curious", "thorough"],
        "tools": ["web_fetch", "content_extract"],
        "capabilities": ["web_research"],
        "goal": "Fetch, extract, and synthesize web content for research and analysis",
        "stats": {"charisma": 50, "elegance": 40, "confidence": 65, "warmth": 55, "level": 20},
        "avatar_color": (41, 128, 185),  # ocean blue
        "mcp_server": {
            "name": "mcp-web",
            "description": "Web fetch + main-content extraction",
            "default_port": 9112,
            "source": {"type": "external", "git": "https://github.com/HomePilotAI/mcp-servers", "ref": "v0.1.0", "subdir": "servers/mcp-web"},
            "transport": "HTTP", "protocol": "MCP",
            "tools_provided": ["hp.web.web.fetch", "hp.web.web.extract_main"],
            "health_check": {"method": "POST", "path": "/rpc", "body": {"jsonrpc": "2.0", "method": "initialize", "id": 1}},
        },
    },
    # ── 4. Soren Lindqvist — Shell Safe ──────────────────────────────────
    {
        "slug": "soren",
        "id": "soren_shell_operator",
        "name": "Soren Lindqvist",
        "role": "Automation Operator",
        "class_id": "assistant",
        "tone": "Calm, methodical, safety-first",
        "short": "Automation operator — runs safe shell commands for diagnostics and tasks",
        "backstory": (
            "Soren is a former sysadmin from Stockholm who managed infrastructure for "
            "Nordic banks. He treats every command like a surgical instrument — precise, "
            "measured, and always with a rollback plan. He will never run anything he "
            "hasn't reviewed first."
        ),
        "system_prompt": (
            "You are Soren Lindqvist, an Automation Operator.\n"
            "You specialize in running safe, allowlisted shell commands for automation "
            "and system diagnostics.\n\n"
            "Rules:\n"
            "- NEVER run destructive commands (rm -rf, dd, mkfs, etc.).\n"
            "- Only execute commands from the approved allowlist.\n"
            "- Explain what each command does before running it.\n"
            "- Show command output clearly and interpret results.\n"
            "- If a command seems risky, refuse and explain why."
        ),
        "tags": ["shell", "automation", "devops"],
        "style_tags": ["Sysadmin", "Nordic"],
        "tone_tags": ["calm", "methodical"],
        "tools": ["shell_allowlist", "shell_run"],
        "capabilities": ["shell_safe"],
        "goal": "Execute safe shell commands for automation, monitoring, and diagnostics",
        "stats": {"charisma": 25, "elegance": 20, "confidence": 80, "warmth": 30, "level": 30},
        "avatar_color": (39, 174, 96),  # green
        "mcp_server": {
            "name": "mcp-shell-safe",
            "description": "Restricted local shell command execution (allowlist)",
            "default_port": 9113,
            "source": {"type": "external", "git": "https://github.com/HomePilotAI/mcp-servers", "ref": "v0.1.0", "subdir": "servers/mcp-shell-safe"},
            "transport": "HTTP", "protocol": "MCP",
            "tools_provided": ["hp.shell_safe.shell.allowed", "hp.shell_safe.shell.run"],
            "health_check": {"method": "POST", "path": "/rpc", "body": {"jsonrpc": "2.0", "method": "initialize", "id": 1}},
        },
    },
    # ── 5. Priya Sharma — Gmail ──────────────────────────────────────────
    {
        "slug": "priya",
        "id": "priya_inbox_alchemist",
        "name": "Priya Sharma",
        "role": "Email Manager",
        "class_id": "secretary",
        "tone": "Professional, efficient, approachable",
        "short": "Email manager — searches, reads, drafts, and sends Gmail messages",
        "backstory": (
            "Priya managed communications for a Fortune 500 CEO in Mumbai before going "
            "freelance. She can tame any inbox — finding that critical email from three "
            "months ago, drafting the perfect reply, and flagging what needs attention "
            "right now."
        ),
        "system_prompt": (
            "You are Priya Sharma, an Email Manager.\n"
            "You specialize in searching, reading, drafting, and sending Gmail messages.\n"
            "You help users manage their inbox efficiently and communicate professionally.\n\n"
            "Rules:\n"
            "- Search and read emails freely to help users find what they need.\n"
            "- For drafting: show the draft and get approval before saving.\n"
            "- For sending: ALWAYS confirm before sending any email.\n"
            "- Suggest concise, professional responses.\n"
            "- Flag urgent or time-sensitive messages."
        ),
        "tags": ["email", "gmail", "inbox"],
        "style_tags": ["Executive", "Professional"],
        "tone_tags": ["efficient", "warm"],
        "tools": ["gmail_search", "gmail_read", "gmail_draft", "gmail_send"],
        "capabilities": ["gmail"],
        "goal": "Manage Gmail inbox — search, read, draft, and send messages efficiently",
        "stats": {"charisma": 65, "elegance": 70, "confidence": 60, "warmth": 75, "level": 25},
        "avatar_color": (192, 57, 43),  # warm red
        "mcp_server": {
            "name": "mcp-gmail",
            "description": "Gmail tools via Google APIs (OAuth required)",
            "default_port": 9114,
            "source": {"type": "external", "git": "https://github.com/HomePilotAI/mcp-servers", "ref": "v0.1.0", "subdir": "servers/mcp-gmail"},
            "transport": "HTTP", "protocol": "MCP",
            "tools_provided": ["hp.gmail.gmail.search", "hp.gmail.gmail.read", "hp.gmail.gmail.draft", "hp.gmail.gmail.send"],
            "health_check": {"method": "POST", "path": "/rpc", "body": {"jsonrpc": "2.0", "method": "initialize", "id": 1}},
        },
    },
    # ── 6. Luca Moretti — Google Calendar ────────────────────────────────
    {
        "slug": "luca",
        "id": "luca_calendar_strategist",
        "name": "Luca Moretti",
        "role": "Calendar Strategist",
        "class_id": "secretary",
        "tone": "Punctual, strategic, upbeat",
        "short": "Calendar strategist — plans, searches, and manages Google Calendar events",
        "backstory": (
            "Luca was an event planner in Milan who orchestrated conferences for thousands. "
            "He sees time as a canvas — every block should be intentional. He'll help you "
            "find free slots, avoid double-bookings, and build a schedule that actually "
            "works for your energy levels."
        ),
        "system_prompt": (
            "You are Luca Moretti, a Calendar Strategist.\n"
            "You specialize in managing Google Calendar — listing events, finding free time, "
            "and creating well-structured calendar entries.\n\n"
            "Rules:\n"
            "- List and search events freely to help users understand their schedule.\n"
            "- For creating/modifying events: confirm details before saving.\n"
            "- Suggest optimal meeting times based on availability.\n"
            "- Warn about conflicts or back-to-back meetings.\n"
            "- Be mindful of time zones."
        ),
        "tags": ["calendar", "schedule", "planning"],
        "style_tags": ["Planner", "Energetic"],
        "tone_tags": ["punctual", "strategic"],
        "tools": ["gcal_list", "gcal_search", "gcal_read", "gcal_create"],
        "capabilities": ["google_calendar"],
        "goal": "Manage Google Calendar — plan schedules, find free time, and organize events",
        "stats": {"charisma": 60, "elegance": 55, "confidence": 55, "warmth": 70, "level": 21},
        "avatar_color": (243, 156, 18),  # warm gold
        "mcp_server": {
            "name": "mcp-google-calendar",
            "description": "Google Calendar tools via Google APIs (OAuth required)",
            "default_port": 9115,
            "source": {"type": "external", "git": "https://github.com/HomePilotAI/mcp-servers", "ref": "v0.1.0", "subdir": "servers/mcp-google-calendar"},
            "transport": "HTTP", "protocol": "MCP",
            "tools_provided": ["hp.google_calendar.gcal.list_events", "hp.google_calendar.gcal.search", "hp.google_calendar.gcal.read_event", "hp.google_calendar.gcal.create_event"],
            "health_check": {"method": "POST", "path": "/rpc", "body": {"jsonrpc": "2.0", "method": "initialize", "id": 1}},
        },
    },
    # ── 7. Diana Brooks — Microsoft Graph ────────────────────────────────
    {
        "slug": "diana",
        "id": "diana_office_navigator",
        "name": "Diana Brooks",
        "role": "Office Navigator",
        "class_id": "secretary",
        "tone": "Corporate-savvy, articulate, poised",
        "short": "Office navigator — manages Outlook mail and calendar via Microsoft 365",
        "backstory": (
            "Diana spent years as an executive assistant at a Wall Street firm, mastering "
            "every corner of Microsoft 365. Outlook, Teams, SharePoint — she knows every "
            "shortcut and hidden feature. She bridges the gap between enterprise tools and "
            "getting things done."
        ),
        "system_prompt": (
            "You are Diana Brooks, an Office Navigator.\n"
            "You specialize in Outlook email and calendar management via Microsoft Graph.\n"
            "You help users navigate their Microsoft 365 environment efficiently.\n\n"
            "Rules:\n"
            "- Search and read mail/calendar freely.\n"
            "- For drafting or sending mail: confirm before executing.\n"
            "- Present information in clean, corporate-appropriate format.\n"
            "- Help with meeting scheduling across time zones.\n"
            "- Flag important items that need attention."
        ),
        "tags": ["outlook", "microsoft", "office365"],
        "style_tags": ["Corporate", "Polished"],
        "tone_tags": ["articulate", "poised"],
        "tools": ["graph_mail_search", "graph_mail_read", "graph_mail_draft", "graph_mail_send", "graph_cal_list", "graph_cal_read"],
        "capabilities": ["microsoft_graph"],
        "goal": "Navigate Microsoft 365 — manage Outlook email and calendar via Graph API",
        "stats": {"charisma": 55, "elegance": 75, "confidence": 70, "warmth": 50, "level": 27},
        "avatar_color": (0, 120, 212),  # Microsoft blue
        "mcp_server": {
            "name": "mcp-microsoft-graph",
            "description": "Outlook Mail + Calendar via Microsoft Graph (OAuth device code)",
            "default_port": 9116,
            "source": {"type": "external", "git": "https://github.com/HomePilotAI/mcp-servers", "ref": "v0.1.0", "subdir": "servers/mcp-microsoft-graph"},
            "transport": "HTTP", "protocol": "MCP",
            "tools_provided": [
                "hp.microsoft_graph.graph.mail.search", "hp.microsoft_graph.graph.mail.read",
                "hp.microsoft_graph.graph.mail.draft", "hp.microsoft_graph.graph.mail.send",
                "hp.microsoft_graph.graph.calendar.list_events", "hp.microsoft_graph.graph.calendar.read_event",
            ],
            "health_check": {"method": "POST", "path": "/rpc", "body": {"jsonrpc": "2.0", "method": "initialize", "id": 1}},
        },
    },
    # ── 8. Kai Tanaka — Slack ────────────────────────────────────────────
    {
        "slug": "kai",
        "id": "kai_channel_whisperer",
        "name": "Kai Tanaka",
        "role": "Comms Specialist",
        "class_id": "assistant",
        "tone": "Friendly, concise, team-oriented",
        "short": "Comms specialist — reads, summarizes, and posts to Slack channels",
        "backstory": (
            "Kai was a community manager for a Tokyo gaming studio before pivoting to "
            "internal comms at a remote-first startup. He has an uncanny ability to catch "
            "the pulse of a team through their Slack channels — knowing who needs help, "
            "what decisions are stuck, and when to surface the right message."
        ),
        "system_prompt": (
            "You are Kai Tanaka, a Comms Specialist.\n"
            "You specialize in Slack communication — reading channels, searching messages, "
            "summarizing discussions, and posting updates.\n\n"
            "Rules:\n"
            "- Read and search channels freely to provide summaries.\n"
            "- For posting messages: ALWAYS confirm content and channel before sending.\n"
            "- Summarize long threads into actionable bullet points.\n"
            "- Highlight decisions, action items, and blockers.\n"
            "- Keep your own messages concise and team-friendly."
        ),
        "tags": ["slack", "team", "communication"],
        "style_tags": ["Casual", "Team-player"],
        "tone_tags": ["friendly", "concise"],
        "tools": ["slack_channels", "slack_history", "slack_search", "slack_post"],
        "capabilities": ["slack"],
        "goal": "Manage Slack communications — read, summarize, and post team messages",
        "stats": {"charisma": 75, "elegance": 35, "confidence": 50, "warmth": 80, "level": 19},
        "avatar_color": (78, 29, 105),  # Slack purple
        "mcp_server": {
            "name": "mcp-slack",
            "description": "Slack tools (OAuth or token)",
            "default_port": 9117,
            "source": {"type": "external", "git": "https://github.com/HomePilotAI/mcp-servers", "ref": "v0.1.0", "subdir": "servers/mcp-slack"},
            "transport": "HTTP", "protocol": "MCP",
            "tools_provided": ["hp.slack.slack.channels.list", "hp.slack.slack.channel.history", "hp.slack.slack.messages.search", "hp.slack.slack.message.post"],
            "health_check": {"method": "POST", "path": "/rpc", "body": {"jsonrpc": "2.0", "method": "initialize", "id": 1}},
        },
    },
    # ── 9. Raven Okafor — GitHub ─────────────────────────────────────────
    {
        "slug": "raven",
        "id": "raven_code_reviewer",
        "name": "Raven Okafor",
        "role": "Dev Workflow Assistant",
        "class_id": "assistant",
        "tone": "Direct, technical, constructive",
        "short": "Dev workflow assistant — reviews PRs, tracks issues, and manages GitHub",
        "backstory": (
            "Raven is a senior engineer from Lagos who has reviewed over 10,000 pull "
            "requests across open-source and enterprise projects. She sees patterns in "
            "code changes that others miss, writes actionable issue reports, and keeps "
            "development workflows humming smoothly."
        ),
        "system_prompt": (
            "You are Raven Okafor, a Dev Workflow Assistant.\n"
            "You specialize in GitHub operations — reviewing PRs, searching issues, "
            "tracking CI status, and managing repositories.\n\n"
            "Rules:\n"
            "- List, search, and read repos/issues/PRs freely.\n"
            "- For creating issues or commenting: confirm content first.\n"
            "- Provide actionable, specific code review feedback.\n"
            "- Highlight breaking changes and security concerns.\n"
            "- Use technical language — your audience is developers."
        ),
        "tags": ["github", "code-review", "devops"],
        "style_tags": ["Engineer", "Open-source"],
        "tone_tags": ["direct", "technical"],
        "tools": ["github_repos", "github_issues", "github_prs", "github_pr_read", "github_issue_create"],
        "capabilities": ["github"],
        "goal": "Manage GitHub workflows — review PRs, track issues, and maintain repositories",
        "stats": {"charisma": 40, "elegance": 30, "confidence": 85, "warmth": 35, "level": 28},
        "avatar_color": (36, 41, 46),  # GitHub dark
        "mcp_server": {
            "name": "mcp-github",
            "description": "GitHub repo/issues/PRs tools (OAuth or PAT)",
            "default_port": 9118,
            "source": {"type": "external", "git": "https://github.com/HomePilotAI/mcp-servers", "ref": "v0.1.0", "subdir": "servers/mcp-github"},
            "transport": "HTTP", "protocol": "MCP",
            "tools_provided": ["hp.github.github.repos.list", "hp.github.github.issues.search", "hp.github.github.prs.list", "hp.github.github.pr.read", "hp.github.github.issue.create"],
            "health_check": {"method": "POST", "path": "/rpc", "body": {"jsonrpc": "2.0", "method": "initialize", "id": 1}},
        },
    },
    # ── 10. Elena Voss — Notion ──────────────────────────────────────────
    {
        "slug": "elena",
        "id": "elena_knowledge_curator",
        "name": "Elena Voss",
        "role": "Knowledge Curator",
        "class_id": "assistant",
        "tone": "Thoughtful, structured, knowledge-driven",
        "short": "Knowledge curator — searches, reads, and updates your Notion workspace",
        "backstory": (
            "Elena was a knowledge manager at a Berlin think tank, designing information "
            "architectures for policy researchers. She treats every Notion page like a "
            "living document — cross-referenced, well-tagged, and always up to date. If "
            "knowledge exists, she'll find it. If it doesn't, she'll help you create it."
        ),
        "system_prompt": (
            "You are Elena Voss, a Knowledge Curator.\n"
            "You specialize in Notion workspace management — searching pages, reading "
            "content, and appending updates to knowledge bases.\n\n"
            "Rules:\n"
            "- Search and read pages freely to answer questions.\n"
            "- For appending or modifying content: confirm changes first.\n"
            "- Suggest better page structure when content is disorganized.\n"
            "- Cross-reference related pages to build connections.\n"
            "- Present Notion content in clean, readable format."
        ),
        "tags": ["notion", "knowledge", "documentation"],
        "style_tags": ["Academic", "Methodical"],
        "tone_tags": ["thoughtful", "structured"],
        "tools": ["notion_search", "notion_read", "notion_append"],
        "capabilities": ["notion"],
        "goal": "Curate knowledge in Notion — search, read, and maintain documentation",
        "stats": {"charisma": 45, "elegance": 60, "confidence": 65, "warmth": 60, "level": 23},
        "avatar_color": (0, 0, 0),  # Notion black
        "mcp_server": {
            "name": "mcp-notion",
            "description": "Notion search/read/append tools (OAuth or integration token)",
            "default_port": 9119,
            "source": {"type": "external", "git": "https://github.com/HomePilotAI/mcp-servers", "ref": "v0.1.0", "subdir": "servers/mcp-notion"},
            "transport": "HTTP", "protocol": "MCP",
            "tools_provided": ["hp.notion.notion.search", "hp.notion.notion.page.read", "hp.notion.notion.page.append"],
            "health_check": {"method": "POST", "path": "/rpc", "body": {"jsonrpc": "2.0", "method": "initialize", "id": 1}},
        },
    },
]

# ---------------------------------------------------------------------------
# Pure-Python PNG generator (no Pillow dependency required)
# ---------------------------------------------------------------------------

def _create_png_bytes(width: int, height: int, bg_color: tuple[int, int, int],
                      initials: str, text_color: tuple[int, int, int] = (255, 255, 255)) -> bytes:
    """
    Create a simple PNG avatar with colored background and centered initials.
    Uses only stdlib (struct, zlib) — no Pillow required.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        return _create_png_pillow(width, height, bg_color, initials, text_color)
    except ImportError:
        return _create_png_raw(width, height, bg_color)


def _create_png_pillow(width: int, height: int, bg_color: tuple, initials: str,
                       text_color: tuple) -> bytes:
    """Create avatar with Pillow (nicer text rendering)."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # Try to use a decent font, fall back to default
    font_size = width // 3
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", font_size)
        except (OSError, IOError):
            font = ImageFont.load_default()

    # Center text
    bbox = draw.textbbox((0, 0), initials, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (width - tw) // 2
    y = (height - th) // 2 - bbox[1]  # Adjust for font ascent
    draw.text((x, y), initials, fill=text_color, font=font)

    # Add subtle gradient overlay for depth
    for row in range(height):
        alpha = int(40 * (row / height))  # subtle darkening toward bottom
        for col in range(width):
            r, g, b = img.getpixel((col, row))
            img.putpixel((col, row), (max(0, r - alpha), max(0, g - alpha), max(0, b - alpha)))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _create_png_raw(width: int, height: int, bg_color: tuple) -> bytes:
    """Fallback: create solid-color PNG with stdlib only."""
    def make_chunk(chunk_type: bytes, data: bytes) -> bytes:
        chunk = chunk_type + data
        return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)

    # IHDR
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    # IDAT
    raw_rows = b""
    for _ in range(height):
        raw_rows += b"\x00" + bytes(bg_color) * width
    idat = zlib.compress(raw_rows)

    png = b"\x89PNG\r\n\x1a\n"
    png += make_chunk(b"IHDR", ihdr)
    png += make_chunk(b"IDAT", idat)
    png += make_chunk(b"IEND", b"")
    return png


def _create_webp_thumb(png_bytes: bytes, size: int = 256) -> bytes:
    """Create WebP thumbnail from PNG bytes. Falls back to PNG if Pillow unavailable."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(png_bytes))
        img = img.resize((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        try:
            img.save(buf, format="WEBP", quality=85)
        except Exception:
            # WebP not supported, use PNG
            img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        # Return resized PNG using raw method
        return png_bytes  # fallback: use full PNG as thumb


# ---------------------------------------------------------------------------
# Persona file generators
# ---------------------------------------------------------------------------

def _save_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _get_initials(name: str) -> str:
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return name[:2].upper()


def generate_persona(sample_dir: Path, p: dict) -> dict:
    """Generate a single persona folder + .hpersona package. Returns registry item."""
    slug = p["slug"]
    persona_dir = sample_dir / slug

    # Safety: never touch protected folders
    if slug in PROTECTED:
        raise ValueError(f"Cannot overwrite protected persona: {slug}")

    # Clean and recreate
    if persona_dir.exists():
        shutil.rmtree(persona_dir)

    # Create directory structure
    for subdir in ["blueprint", "dependencies", "preview", "assets"]:
        (persona_dir / subdir).mkdir(parents=True, exist_ok=True)

    initials = _get_initials(p["name"])
    avatar_filename = f"avatar_{slug}.png"
    thumb_filename = f"thumb_avatar_{slug}.webp"

    # ── manifest.json ────────────────────────────────────────────────────
    _save_json(persona_dir / "manifest.json", {
        "kind": "homepilot.persona",
        "schema_version": 2,
        "package_version": 2,
        "project_type": "persona",
        "source_homepilot_version": HP_VERSION,
        "content_rating": "sfw",
        "created_at": UTC_NOW,
        "contents": {
            "has_avatar": True,
            "has_outfits": False,
            "outfit_count": 0,
            "has_tool_dependencies": True,
            "has_mcp_servers": True,
            "has_a2a_agents": False,
            "has_model_requirements": False,
        },
        "capability_summary": {
            "personality_tools": p["tools"],
            "capabilities": p["capabilities"],
            "mcp_servers_count": 1,
            "a2a_agents_count": 0,
        },
    })

    # ── blueprint/persona_agent.json ─────────────────────────────────────
    _save_json(persona_dir / "blueprint" / "persona_agent.json", {
        "id": p["id"],
        "label": p["name"],
        "role": p["role"],
        "category": "sfw",
        "system_prompt": p["system_prompt"],
        "response_style": {"tone": p["tone"]},
        "allowed_tools": p["tools"],
    })

    # ── blueprint/persona_appearance.json ────────────────────────────────
    _save_json(persona_dir / "blueprint" / "persona_appearance.json", {
        "style_preset": "casual",
        "aspect_ratio": "1:1",
        "img_preset": "med",
        "sets": [],
        "selected_filename": avatar_filename,
        "selected_thumb_filename": thumb_filename,
    })

    # ── blueprint/agentic.json ───────────────────────────────────────────
    _save_json(persona_dir / "blueprint" / "agentic.json", {
        "goal": p["goal"],
        "capabilities": p["capabilities"],
        "tool_source": "all",
    })

    # ── dependencies/tools.json ──────────────────────────────────────────
    _save_json(persona_dir / "dependencies" / "tools.json", {
        "schema_version": 1,
        "personality_tools": {
            "description": "Simple tool IDs from PersonalityAgent.allowed_tools",
            "tools": p["tools"],
        },
        "forge_tools": {
            "description": "Tool references from Context Forge / MCP",
            "tools": p["mcp_server"]["tools_provided"],
        },
        "tool_schemas": [],
        "capability_summary": {
            "required": p["capabilities"],
            "optional": [],
        },
    })

    # ── dependencies/mcp_servers.json ────────────────────────────────────
    _save_json(persona_dir / "dependencies" / "mcp_servers.json", {
        "schema_version": 1,
        "servers": [p["mcp_server"]],
    })

    # ── dependencies/models.json ─────────────────────────────────────────
    _save_json(persona_dir / "dependencies" / "models.json", {
        "schema_version": 1,
        "image_models": [],
        "llm_hint": {
            "min_capability": "7b",
            "recommended": "llama3:8b",
            "note": "Any 7B+ instruction-tuned model works",
        },
    })

    # ── dependencies/suite.json ──────────────────────────────────────────
    _save_json(persona_dir / "dependencies" / "suite.json", {
        "schema_version": 1,
        "recommended_suite": "default_home",
        "tool_source": "all",
        "forge_sync_required": False,
    })

    # ── dependencies/a2a_agents.json ─────────────────────────────────────
    _save_json(persona_dir / "dependencies" / "a2a_agents.json", {
        "schema_version": 1,
        "agents": [],
    })

    # ── preview/card.json ────────────────────────────────────────────────
    _save_json(persona_dir / "preview" / "card.json", {
        "name": p["name"],
        "role": p["role"],
        "short": p["short"],
        "class_id": p["class_id"],
        "tone": p["tone"],
        "tags": p["tags"],
        "tools": p["tools"],
        "content_rating": "sfw",
        "has_avatar": True,
        "stats": p["stats"],
        "style_tags": p["style_tags"],
        "tone_tags": p["tone_tags"],
        "backstory": p["backstory"],
    })

    # ── assets/ — generate avatar + thumbnail ────────────────────────────
    avatar_png = _create_png_bytes(512, 512, p["avatar_color"], initials)
    (persona_dir / "assets" / avatar_filename).write_bytes(avatar_png)

    thumb_bytes = _create_webp_thumb(avatar_png, 256)
    thumb_path = persona_dir / "assets" / thumb_filename
    # If WebP failed, save as PNG with .webp name (HomePilot handles both)
    thumb_path.write_bytes(thumb_bytes)

    # ── Create .hpersona ZIP ─────────────────────────────────────────────
    hpersona_path = sample_dir / f"{slug}.hpersona"
    if hpersona_path.exists():
        hpersona_path.unlink()
    with zipfile.ZipFile(hpersona_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(persona_dir):
            for fn in files:
                full = Path(root) / fn
                rel = full.relative_to(persona_dir)
                zf.write(full, arcname=str(rel))

    # ── Registry item ────────────────────────────────────────────────────
    size_bytes = hpersona_path.stat().st_size
    return {
        "id": p["id"],
        "name": p["name"],
        "short": p["short"],
        "tags": p["tags"],
        "nsfw": False,
        "author": AUTHOR,
        "downloads": 0,
        "class_id": p["class_id"],
        "has_avatar": True,
        "latest": {
            "version": "1.0.0",
            "package_url": f"/p/{p['id']}/1.0.0",
            "preview_url": f"/v/{p['id']}/1.0.0",
            "card_url": f"/c/{p['id']}/1.0.0",
            "sha256": hashlib.sha256(hpersona_path.read_bytes()).hexdigest(),
            "size_bytes": size_bytes,
        },
    }


def update_registry(sample_dir: Path, new_items: list[dict]) -> None:
    """Merge new persona items into registry.json (additive — keeps existing entries)."""
    reg_path = sample_dir / "registry.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8"))

    existing = {item["id"]: item for item in reg.get("items", [])}
    for item in new_items:
        existing[item["id"]] = item

    merged = sorted(existing.values(), key=lambda x: x.get("name", "").lower())
    reg["items"] = merged
    reg["total"] = len(merged)
    reg["generated_at"] = UTC_NOW

    _save_json(reg_path, reg)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    sample_dir = SCRIPT_DIR
    print(f"Generating 10 community personas in: {sample_dir}")
    print(f"Protected (untouched): {', '.join(sorted(PROTECTED))}")
    print()

    registry_items = []
    for p in PERSONAS:
        print(f"  Creating {p['name']:20s} ({p['slug']}) -> {p['mcp_server']['name']} :{p['mcp_server']['default_port']}")
        item = generate_persona(sample_dir, p)
        registry_items.append(item)

    print()
    update_registry(sample_dir, registry_items)

    print(f"Done! Generated {len(PERSONAS)} personas:")
    for p in PERSONAS:
        print(f"  {sample_dir / p['slug']}/")
        print(f"  {sample_dir / (p['slug'] + '.hpersona')}")
    print(f"\nRegistry updated: {sample_dir / 'registry.json'}")
    print(f"Total personas in registry: {len(registry_items) + len(PROTECTED)}")


if __name__ == "__main__":
    main()
