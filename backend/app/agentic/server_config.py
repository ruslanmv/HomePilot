"""MCP Server Configuration — schema registry, save/load, and restart logic.

Provides a typed config schema for each `requires_config` value in the
server catalog (GOOGLE_OAUTH, SLACK_TOKEN, GITHUB_TOKEN, etc.).

Config lifecycle:
  1. GET  /servers/{id}/config  → returns schema + current (masked) values
  2. POST /servers/{id}/config  → saves to .env, stores in secrets vault, restarts server
  3. POST /servers/{id}/config/test → validates without saving (dry-run health check)
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("homepilot.agentic.server_config")


# ── Field definition ──────────────────────────────────────────────────────


@dataclass
class ConfigField:
    """A single config field for an MCP server."""
    key: str
    label: str
    type: str = "text"  # text | secret | toggle | select
    required: bool = True
    hint: str = ""
    placeholder: str = ""
    default: str = ""
    options: List[str] = field(default_factory=list)
    condition: str = ""  # e.g. "MS_AUTH_METHOD=client_secret"

    def to_dict(self, value: str = "") -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "value": value,
            "hint": self.hint,
            "placeholder": self.placeholder,
        }
        if self.default:
            d["default"] = self.default
        if self.options:
            d["options"] = self.options
        if self.condition:
            d["condition"] = self.condition
        return d


# ── Setup guide definition ────────────────────────────────────────────────


@dataclass
class SetupStep:
    title: str
    description: str
    link_label: str = ""
    link_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"title": self.title, "description": self.description}
        if self.link_label and self.link_url:
            d["link"] = {"label": self.link_label, "url": self.link_url}
        return d


@dataclass
class SetupGuide:
    title: str
    subtitle: str = ""
    steps: List[SetupStep] = field(default_factory=list)
    doc_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "steps": [s.to_dict() for s in self.steps],
            "doc_url": self.doc_url,
        }


# ── Config schemas per requires_config value ──────────────────────────────

CONFIG_SCHEMAS: Dict[str, List[ConfigField]] = {
    "GOOGLE_OAUTH": [
        ConfigField(
            key="GOOGLE_CLIENT_ID",
            label="Client ID",
            hint="From Google Cloud Console → APIs & Services → Credentials",
            placeholder="xxxxxxxxxxxx.apps.googleusercontent.com",
        ),
        ConfigField(
            key="GOOGLE_CLIENT_SECRET",
            label="Client Secret",
            type="secret",
            hint="OAuth 2.0 client secret",
            placeholder="GOCSPX-xxxxxxxxxxxx",
        ),
        ConfigField(
            key="WRITE_ENABLED",
            label="Allow write operations (send emails, create events)",
            type="toggle",
            required=False,
            default="false",
        ),
    ],
    "SLACK_TOKEN": [
        ConfigField(
            key="SLACK_BOT_TOKEN",
            label="Bot Token",
            type="secret",
            hint="From api.slack.com/apps → OAuth & Permissions → Bot User OAuth Token",
            placeholder="xoxb-xxxxxxxxxxxx-xxxxxxxxxxxx",
        ),
        ConfigField(
            key="SLACK_APP_TOKEN",
            label="App-Level Token (optional)",
            type="secret",
            required=False,
            hint="Only needed for Socket Mode. From api.slack.com/apps → Basic Information → App-Level Tokens",
            placeholder="xapp-x-xxxxxxxxxxxx",
        ),
        ConfigField(
            key="SLACK_TEAM_ID",
            label="Workspace ID (optional)",
            required=False,
            hint="Restrict to a specific workspace. Find it in workspace settings.",
            placeholder="T0XXXXXXXXX",
        ),
        ConfigField(
            key="WRITE_ENABLED",
            label="Allow posting messages",
            type="toggle",
            required=False,
            default="false",
        ),
    ],
    "GITHUB_TOKEN": [
        ConfigField(
            key="GITHUB_TOKEN",
            label="Personal Access Token",
            type="secret",
            hint="From github.com/settings/tokens → Generate new token (classic or fine-grained)",
            placeholder="ghp_xxxxxxxxxxxxxxxxxxxx",
        ),
        ConfigField(
            key="GITHUB_ORG",
            label="Organization (optional)",
            required=False,
            hint="Restrict to a specific org. Leave empty for all accessible repos.",
            placeholder="my-org",
        ),
        ConfigField(
            key="WRITE_ENABLED",
            label="Allow write operations (create issues, PRs)",
            type="toggle",
            required=False,
            default="false",
        ),
    ],
    "NOTION_TOKEN": [
        ConfigField(
            key="NOTION_TOKEN",
            label="Integration Token",
            type="secret",
            hint="From notion.so/my-integrations → Create or select integration → Internal Integration Token",
            placeholder="ntn_xxxxxxxxxxxxxxxxxxxx",
        ),
        ConfigField(
            key="WRITE_ENABLED",
            label="Allow creating/updating pages",
            type="toggle",
            required=False,
            default="false",
        ),
    ],
    "MS_GRAPH_TOKEN": [
        ConfigField(
            key="MS_CLIENT_ID",
            label="Application (client) ID",
            hint="From Azure Portal → App registrations → Overview",
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        ),
        ConfigField(
            key="MS_TENANT_ID",
            label="Directory (tenant) ID",
            hint="Use 'common' for multi-tenant or your specific tenant ID",
            placeholder="common",
            default="common",
        ),
        ConfigField(
            key="MS_AUTH_METHOD",
            label="Authentication method",
            type="select",
            options=["device_code", "client_secret"],
            default="device_code",
            hint="device_code: interactive login (recommended). client_secret: app-only access.",
        ),
        ConfigField(
            key="MS_CLIENT_SECRET",
            label="Client Secret",
            type="secret",
            required=False,
            condition="MS_AUTH_METHOD=client_secret",
            hint="Only required when using client_secret auth method",
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        ),
        ConfigField(
            key="WRITE_ENABLED",
            label="Allow write operations (send emails, create events)",
            type="toggle",
            required=False,
            default="false",
        ),
    ],
    "MS_TEAMS_AUTH": [
        ConfigField(
            key="MS_CLIENT_ID",
            label="Application (client) ID",
            hint="From Azure Portal → App registrations → Overview",
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        ),
        ConfigField(
            key="MS_TENANT_ID",
            label="Directory (tenant) ID",
            hint="Use 'common' for multi-tenant or your specific tenant ID",
            placeholder="common",
            default="common",
        ),
        ConfigField(
            key="MS_AUTH_METHOD",
            label="Authentication method",
            type="select",
            options=["device_code", "client_secret"],
            default="device_code",
            hint="device_code: interactive login (recommended). client_secret: app-only access.",
        ),
        ConfigField(
            key="MS_CLIENT_SECRET",
            label="Client Secret",
            type="secret",
            required=False,
            condition="MS_AUTH_METHOD=client_secret",
            hint="Only required when using client_secret auth method",
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        ),
        ConfigField(
            key="WRITE_ENABLED",
            label="Allow posting messages",
            type="toggle",
            required=False,
            default="false",
        ),
    ],
}

# ── Setup guides per requires_config value ────────────────────────────────

SETUP_GUIDES: Dict[str, SetupGuide] = {
    "GOOGLE_OAUTH": SetupGuide(
        title="Connect Google",
        subtitle="Gmail, Calendar, and other Google services",
        doc_url="https://console.cloud.google.com/apis/credentials",
        steps=[
            SetupStep(
                "Create a Google Cloud project",
                "Go to the Google Cloud Console, create a new project (or select an existing one), then enable the Gmail API and/or Google Calendar API.",
                "Open Google Cloud Console",
                "https://console.cloud.google.com/apis/library",
            ),
            SetupStep(
                "Create OAuth credentials",
                "Navigate to APIs & Services → Credentials → Create Credentials → OAuth client ID. Choose 'Desktop app' as the application type.",
                "Open Credentials Page",
                "https://console.cloud.google.com/apis/credentials",
            ),
            SetupStep(
                "Copy Client ID & Secret",
                "After creating the OAuth client, copy the Client ID and Client Secret. Paste them in the fields below.",
            ),
        ],
    ),
    "SLACK_TOKEN": SetupGuide(
        title="Connect Slack",
        subtitle="Read channels, search messages, post updates",
        doc_url="https://api.slack.com/apps",
        steps=[
            SetupStep(
                "Create a Slack App",
                "Go to the Slack API portal and create a new app. Choose 'From scratch' and select your workspace.",
                "Open Slack Apps",
                "https://api.slack.com/apps",
            ),
            SetupStep(
                "Add Bot Scopes",
                "Under OAuth & Permissions, add bot token scopes: channels:read, channels:history, chat:write, users:read, search:read.",
            ),
            SetupStep(
                "Install to Workspace & copy token",
                "Click 'Install to Workspace', authorize, then copy the Bot User OAuth Token (starts with xoxb-).",
            ),
        ],
    ),
    "GITHUB_TOKEN": SetupGuide(
        title="Connect GitHub",
        subtitle="Repositories, issues, pull requests, and code search",
        doc_url="https://github.com/settings/tokens",
        steps=[
            SetupStep(
                "Create a Personal Access Token",
                "Go to GitHub Settings → Developer settings → Personal access tokens → Fine-grained tokens (recommended) or Tokens (classic).",
                "Open GitHub Token Settings",
                "https://github.com/settings/tokens?type=beta",
            ),
            SetupStep(
                "Select scopes",
                "For fine-grained: select repositories and permissions (Contents: read, Issues: read/write, Pull requests: read/write). For classic: select repo, read:org.",
            ),
            SetupStep(
                "Copy & paste",
                "Generate the token, copy it, and paste it below. Tokens are only shown once.",
            ),
        ],
    ),
    "NOTION_TOKEN": SetupGuide(
        title="Connect Notion",
        subtitle="Pages, databases, and workspace search",
        doc_url="https://www.notion.so/my-integrations",
        steps=[
            SetupStep(
                "Create a Notion integration",
                "Go to Notion's integrations page and click 'New integration'. Give it a name and select your workspace.",
                "Open Notion Integrations",
                "https://www.notion.so/my-integrations",
            ),
            SetupStep(
                "Copy the Internal Integration Token",
                "After creating the integration, copy the 'Internal Integration Token' (starts with ntn_).",
            ),
            SetupStep(
                "Share pages with the integration",
                "In Notion, open any page/database you want accessible, click Share → Invite, and add your integration.",
            ),
        ],
    ),
    "MS_GRAPH_TOKEN": SetupGuide(
        title="Connect Microsoft 365",
        subtitle="Outlook mail, calendar, OneDrive, and Microsoft services",
        doc_url="https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
        steps=[
            SetupStep(
                "Register an Azure AD app",
                "Go to Azure Portal → App registrations → New registration. Set 'Supported account types' to your preference.",
                "Open Azure App Registrations",
                "https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
            ),
            SetupStep(
                "Add API permissions",
                "Under API permissions, add Microsoft Graph: Mail.Read, Mail.Send, Calendars.ReadWrite, User.Read (delegated permissions).",
            ),
            SetupStep(
                "Copy Application ID & configure auth",
                "Copy the Application (client) ID from the Overview page. For device_code flow (recommended), enable 'Allow public client flows' under Authentication.",
            ),
        ],
    ),
    "MS_TEAMS_AUTH": SetupGuide(
        title="Connect Microsoft Teams",
        subtitle="Teams channels, messages, and collaboration",
        doc_url="https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
        steps=[
            SetupStep(
                "Register an Azure AD app",
                "Go to Azure Portal → App registrations → New registration. Set redirect URI to 'http://localhost'.",
                "Open Azure App Registrations",
                "https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
            ),
            SetupStep(
                "Add Teams permissions",
                "Under API permissions, add Microsoft Graph: Team.ReadBasic.All, Channel.ReadBasic.All, ChannelMessage.Read.All, Chat.Read (delegated).",
            ),
            SetupStep(
                "Copy Application ID",
                "Copy the Application (client) ID and optionally a client secret, then fill in below.",
            ),
        ],
    ),
}


# ── Server → directory mapping ────────────────────────────────────────────

_SERVER_DIR_MAP: Dict[str, str] = {
    "hp-gmail": "gmail",
    "hp-google-calendar": "google_calendar",
    "hp-microsoft-graph": "microsoft_graph",
    "hp-slack": "slack",
    "hp-github": "github",
    "hp-notion": "notion",
    "hp-teams": "teams",
}


def _server_env_path(server_id: str) -> Optional[Path]:
    """Resolve the .env file path for a builtin server."""
    dirname = _SERVER_DIR_MAP.get(server_id)
    if not dirname:
        return None

    candidates = [
        Path(__file__).resolve().parents[3] / "agentic" / "integrations" / "mcp" / dirname / ".env",
        Path("agentic/integrations/mcp") / dirname / ".env",
        Path(os.environ.get("HOMEPILOT_ROOT", ".")) / "agentic" / "integrations" / "mcp" / dirname / ".env",
    ]
    # Return the first existing path's parent that exists, or the first candidate
    for p in candidates:
        if p.parent.is_dir():
            return p
    return candidates[0]


def _mask_value(val: str) -> str:
    """Mask a secret value for display: show first 4 and last 2 chars."""
    if not val or len(val) < 8:
        return "••••••" if val else ""
    return val[:4] + "••••••" + val[-2:]


# ── Public API ────────────────────────────────────────────────────────────


def get_config_schema(requires_config: str) -> Optional[List[ConfigField]]:
    """Return the config schema for a requires_config value, or None."""
    return CONFIG_SCHEMAS.get(requires_config)


def get_setup_guide(requires_config: str) -> Optional[SetupGuide]:
    """Return the setup guide for a requires_config value, or None."""
    return SETUP_GUIDES.get(requires_config)


def read_server_config(server_id: str, requires_config: str) -> Dict[str, Any]:
    """Read current config values from the server's .env file.

    Returns a dict with schema fields, current (masked) values, and configured status.
    """
    schema = get_config_schema(requires_config)
    if not schema:
        return {"server_id": server_id, "requires_config": requires_config, "configured": False, "fields": []}

    env_path = _server_env_path(server_id)
    current_values: Dict[str, str] = {}
    if env_path and env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line)
                if m:
                    current_values[m.group(1)] = m.group(2)
        except Exception as exc:
            logger.warning("Failed to read %s: %s", env_path, exc)

    # Check if all required fields have values
    configured = all(
        bool(current_values.get(f.key, "").strip())
        for f in schema
        if f.required
    )

    fields = []
    for f in schema:
        raw = current_values.get(f.key, "")
        display = _mask_value(raw) if f.type == "secret" and raw else raw
        fields.append(f.to_dict(value=display))

    guide = get_setup_guide(requires_config)

    result: Dict[str, Any] = {
        "server_id": server_id,
        "requires_config": requires_config,
        "configured": configured,
        "fields": fields,
    }
    if guide:
        result["setup_guide"] = guide.to_dict()

    return result


def save_server_config(server_id: str, requires_config: str, values: Dict[str, str]) -> Dict[str, Any]:
    """Save config values to the server's .env file.

    Preserves comments and non-config lines. Returns success status.
    """
    schema = get_config_schema(requires_config)
    if not schema:
        return {"ok": False, "error": f"Unknown config type: {requires_config}"}

    env_path = _server_env_path(server_id)
    if not env_path:
        return {"ok": False, "error": f"No .env path for server: {server_id}"}

    # Validate required fields
    for f in schema:
        if f.required and not values.get(f.key, "").strip():
            return {"ok": False, "error": f"Missing required field: {f.label}"}

    # Read existing .env or use .env.example as template
    existing_lines: List[str] = []
    example_path = env_path.parent / ".env.example"

    if env_path.exists():
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()
    elif example_path.exists():
        existing_lines = example_path.read_text(encoding="utf-8").splitlines()

    # Build new .env content: update existing keys, append new ones
    schema_keys = {f.key for f in schema}
    written_keys: set = set()
    new_lines: List[str] = []

    for line in existing_lines:
        stripped = line.strip()
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=", stripped)
        if m and m.group(1) in schema_keys:
            key = m.group(1)
            val = values.get(key, "")
            # For toggle fields, convert true/false
            field_def = next((f for f in schema if f.key == key), None)
            if field_def and field_def.type == "toggle":
                val = "true" if val in ("true", "1", True) else "false"
            new_lines.append(f"{key}={val}")
            written_keys.add(key)
        else:
            new_lines.append(line)

    # Append any schema keys not found in the file
    for f in schema:
        if f.key not in written_keys:
            val = values.get(f.key, f.default)
            if f.type == "toggle":
                val = "true" if val in ("true", "1", True) else "false"
            new_lines.append(f"{f.key}={val}")

    # Write
    try:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "error": f"Failed to write .env: {exc}"}

    logger.info("Saved config for %s to %s (%d fields)", server_id, env_path, len(values))
    return {"ok": True, "path": str(env_path)}


def validate_config(requires_config: str, values: Dict[str, str]) -> Dict[str, Any]:
    """Validate config values without saving. Returns validation result."""
    schema = get_config_schema(requires_config)
    if not schema:
        return {"valid": False, "errors": [f"Unknown config type: {requires_config}"]}

    errors: List[str] = []
    for f in schema:
        val = values.get(f.key, "").strip()
        if f.required and not val:
            errors.append(f"'{f.label}' is required")
        # Basic format validation
        if val and f.key == "GOOGLE_CLIENT_ID" and not val.endswith(".apps.googleusercontent.com"):
            errors.append("Client ID should end with .apps.googleusercontent.com")
        if val and f.key == "SLACK_BOT_TOKEN" and not val.startswith("xoxb-"):
            errors.append("Bot Token should start with xoxb-")
        if val and f.key == "GITHUB_TOKEN" and not (val.startswith("ghp_") or val.startswith("github_pat_")):
            errors.append("Token should start with ghp_ or github_pat_")

    return {"valid": len(errors) == 0, "errors": errors}
