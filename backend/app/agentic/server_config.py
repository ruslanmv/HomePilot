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
    # ── Communication: WhatsApp Cloud API (Meta) ───────────────────────
    "WHATSAPP_CLOUD_API": [
        ConfigField(
            key="WHATSAPP_ACCESS_TOKEN",
            label="Access Token",
            type="secret",
            hint="System User token from business.facebook.com → System Users → Generate Token. Select whatsapp_business_messaging + whatsapp_business_management scopes.",
            placeholder="EAAG...",
        ),
        ConfigField(
            key="WHATSAPP_PHONE_NUMBER_ID",
            label="Phone Number ID",
            hint="Meta Business Manager → WhatsApp → API Setup → Phone Number ID (not the number itself).",
            placeholder="1234567890123456",
        ),
        ConfigField(
            key="WHATSAPP_BUSINESS_ACCOUNT_ID",
            label="Business Account ID (WABA ID)",
            required=False,
            hint="Optional; only needed for template list / media uploads.",
            placeholder="9876543210987654",
        ),
        ConfigField(
            key="WHATSAPP_APP_SECRET",
            label="App Secret",
            type="secret",
            hint="From developers.facebook.com → App Dashboard → Settings → Basic → App Secret. Used to verify X-Hub-Signature-256 on inbound webhooks.",
            placeholder="abc123...",
        ),
        ConfigField(
            key="WHATSAPP_WEBHOOK_VERIFY_TOKEN",
            label="Webhook Verify Token",
            type="secret",
            required=False,
            hint="Arbitrary string you choose. Enter the SAME value in Meta → WhatsApp → Configuration → Webhook.",
            placeholder="any-secure-token",
        ),
        ConfigField(
            key="WHATSAPP_DEFAULT_FROM",
            label="Default Sender Display Number",
            required=False,
            hint="E.164 number shown to recipients. Leave empty to use the Phone Number ID's registered number.",
            placeholder="+14155551212",
        ),
        ConfigField(
            key="INSTALL_STATE",
            label="Install state",
            type="select",
            required=False,
            default="INSTALLED_DISABLED",
            options=["INSTALLED_DISABLED", "ENABLED", "DEGRADED", "DISABLED"],
            hint="Set to ENABLED once credentials are validated. Start with INSTALLED_DISABLED for safety.",
        ),
        ConfigField(
            key="WRITE_ENABLED",
            label="Allow outbound sends",
            type="toggle",
            required=False,
            default="false",
            hint="When off, the server stays in DRY_RUN — handlers return preview strings instead of hitting the Cloud API.",
        ),
    ],
    # ── Communication: Telegram Bot API ────────────────────────────────
    "TELEGRAM_BOT": [
        ConfigField(
            key="TELEGRAM_BOT_TOKEN",
            label="Bot Token",
            type="secret",
            hint="From t.me/BotFather → /newbot (or /token for an existing bot). Format: <id>:<hash>",
            placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        ),
        ConfigField(
            key="TELEGRAM_WEBHOOK_SECRET_TOKEN",
            label="Webhook Secret Token",
            type="secret",
            required=False,
            hint="Arbitrary 1–256 chars. Send this to Telegram via setWebhook?secret_token=…; Telegram echoes it back as X-Telegram-Bot-Api-Secret-Token on every webhook.",
            placeholder="any-secure-token",
        ),
        ConfigField(
            key="TELEGRAM_DEFAULT_CHAT_ID",
            label="Default Chat ID (optional)",
            required=False,
            hint="Auto-fill this in send_message. Get it from a test message via getUpdates or by messaging @userinfobot.",
            placeholder="123456789",
        ),
        ConfigField(
            key="INSTALL_STATE",
            label="Install state",
            type="select",
            required=False,
            default="INSTALLED_DISABLED",
            options=["INSTALLED_DISABLED", "ENABLED", "DEGRADED", "DISABLED"],
        ),
        ConfigField(
            key="WRITE_ENABLED",
            label="Allow outbound sends",
            type="toggle",
            required=False,
            default="false",
        ),
    ],
    # ── Communication: VoIP (Twilio / Telnyx / Infobip) ────────────────
    "VOIP_PROVIDER": [
        ConfigField(
            key="TELEPHONY_PROVIDER",
            label="Provider",
            type="select",
            default="twilio",
            options=["twilio", "telnyx", "infobip"],
            hint="Pick the programmable-voice provider that owns your DID.",
        ),
        ConfigField(
            key="TWILIO_ACCOUNT_SID",
            label="Account SID",
            type="secret",
            hint="Twilio Console → Account Info → Account SID. (Telnyx/Infobip: use your equivalent API key here.)",
            placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            condition="TELEPHONY_PROVIDER=twilio",
        ),
        ConfigField(
            key="TWILIO_AUTH_TOKEN",
            label="Auth Token",
            type="secret",
            hint="Twilio Console → Account Info → Auth Token. Also signs webhooks via HMAC-SHA1.",
            placeholder="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            condition="TELEPHONY_PROVIDER=twilio",
        ),
        ConfigField(
            key="VOIP_APP_DID",
            label="App Phone Number (E.164)",
            hint="The ONE phone number this app instance answers on. Must be E.164 (+<country><number>). Single-DID policy rejects inbound calls to any other number.",
            placeholder="+14155551212",
        ),
        ConfigField(
            key="VOIP_DEFAULT_FROM",
            label="Default Outbound From (optional)",
            required=False,
            hint="Override the From number for outbound persona calls. Leave empty to reuse VOIP_APP_DID.",
            placeholder="+14155551212",
        ),
        ConfigField(
            key="VOIP_WEBHOOK_SECRET",
            label="Webhook Signing Secret (optional)",
            type="secret",
            required=False,
            hint="For Twilio, usually the same as Auth Token. For Telnyx/Infobip, the provider-specific webhook secret.",
        ),
        ConfigField(
            key="TELEPHONY_ENABLED",
            label="Enable Ingress (answer inbound calls)",
            type="toggle",
            required=False,
            default="false",
            hint="When off, only outbound tools work. When on, the ingress bridge accepts provider callbacks and creates voice_call sessions.",
        ),
        ConfigField(
            key="INSTALL_STATE",
            label="Install state",
            type="select",
            required=False,
            default="INSTALLED_DISABLED",
            options=["INSTALLED_DISABLED", "ENABLED", "DEGRADED", "DISABLED"],
        ),
        ConfigField(
            key="WRITE_ENABLED",
            label="Allow outbound calls",
            type="toggle",
            required=False,
            default="false",
            hint="Must be ON for the persona to actually place calls. Off = DRY_RUN preview only.",
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
    # ── Communication: WhatsApp Cloud API wizard ───────────────────────
    "WHATSAPP_CLOUD_API": SetupGuide(
        title="WhatsApp Cloud API setup",
        subtitle="Register a Meta Business app, point its webhook at HomePilot, and paste the Access Token + Phone Number ID below.",
        doc_url="https://developers.facebook.com/docs/whatsapp/cloud-api/get-started",
        steps=[
            SetupStep(
                "1. Create or reuse a Meta Business app",
                "Open Meta for Developers → My Apps → Create App → type 'Business'. Give it a name; link it to your Business Manager account.",
                link_label="Open Meta for Developers",
                link_url="https://developers.facebook.com/apps/",
            ),
            SetupStep(
                "2. Add the WhatsApp product",
                "In the app dashboard → Products → Add Product → WhatsApp → Set up. Meta provisions a test phone number automatically so you can start before porting your real DID.",
            ),
            SetupStep(
                "3. Copy the Phone Number ID + Access Token",
                "WhatsApp → API Setup panel shows both values. The temporary 24-hour token is fine for testing; generate a long-lived System User token before production.",
                link_label="System User token howto",
                link_url="https://developers.facebook.com/docs/whatsapp/business-management-api/get-started",
            ),
            SetupStep(
                "4. Set the webhook",
                "WhatsApp → Configuration → Edit callback URL. Point it at https://<your-host>/mcp/whatsapp/webhook, choose a Verify Token (paste the SAME value in the field below), and subscribe to the 'messages' field.",
            ),
            SetupStep(
                "5. Copy the App Secret",
                "App Dashboard → Settings → Basic → App Secret → Show. This is the HMAC-SHA256 key HomePilot uses to verify every inbound webhook.",
            ),
            SetupStep(
                "6. Paste + Save → Test",
                "Fill every field below, flip INSTALL_STATE to ENABLED, hit Save, then Test. A green 'webhook verify: ok' and a dry-run message preview mean you're ready for WRITE_ENABLED=true.",
            ),
        ],
    ),
    # ── Communication: Telegram Bot wizard ─────────────────────────────
    "TELEGRAM_BOT": SetupGuide(
        title="Telegram Bot setup",
        subtitle="Create a bot with @BotFather, choose a webhook secret, then paste the token + secret below.",
        doc_url="https://core.telegram.org/bots/tutorial",
        steps=[
            SetupStep(
                "1. Talk to BotFather",
                "Open Telegram, message @BotFather, send /newbot. Choose a display name (e.g. 'HomePilot Secretary') and a unique username ending in 'bot'. BotFather replies with the Bot Token.",
                link_label="Open BotFather",
                link_url="https://t.me/BotFather",
            ),
            SetupStep(
                "2. Paste the Bot Token below",
                "Copy the 123456:ABC-DEF… string into the 'Bot Token' field. This is a secret — anyone with it can impersonate your bot.",
            ),
            SetupStep(
                "3. Choose a webhook secret token",
                "Pick any 1–256 character string. Paste it in 'Webhook Secret Token' below, and Telegram will echo it back on every webhook so HomePilot can reject spoofed POSTs.",
            ),
            SetupStep(
                "4. Register the webhook with Telegram",
                "Call https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<your-host>/mcp/telegram/webhook&secret_token=<your-secret>. A one-liner curl works fine.",
                link_label="setWebhook reference",
                link_url="https://core.telegram.org/bots/api#setwebhook",
            ),
            SetupStep(
                "5. (Optional) Find your chat ID",
                "Send any message to your new bot, then hit https://api.telegram.org/bot<TOKEN>/getUpdates. The first result's message.chat.id is what goes in 'Default Chat ID'.",
            ),
            SetupStep(
                "6. Save → Test",
                "Fill the fields, flip INSTALL_STATE to ENABLED, Save, then Test. Green = webhook verify works end-to-end.",
            ),
        ],
    ),
    # ── Communication: VoIP / Phone wizard ─────────────────────────────
    "VOIP_PROVIDER": SetupGuide(
        title="VoIP / Phone setup",
        subtitle="Register one phone number (DID) with a programmable-voice provider, point its webhook at HomePilot, and map the DID to a persona.",
        doc_url="https://www.twilio.com/docs/voice/quickstart",
        steps=[
            SetupStep(
                "1. Pick a provider and buy one phone number",
                "Twilio / Telnyx / Infobip all work. In the provider console, buy a phone number ('DID') with Voice capability. Single-DID mode in HomePilot means ONE number per app instance — phase 1 design.",
                link_label="Twilio: buy a number",
                link_url="https://console.twilio.com/us1/develop/phone-numbers/manage/search",
            ),
            SetupStep(
                "2. Paste Account SID + Auth Token",
                "Twilio Console home page shows both under 'Account Info'. For Telnyx/Infobip, use your API key / Public key in the SID field and the secret in Auth Token.",
                link_label="Twilio Console",
                link_url="https://console.twilio.com/",
            ),
            SetupStep(
                "3. Set the App Phone Number (VOIP_APP_DID)",
                "Paste the number you just bought in E.164 format (+<country><number>, e.g. +14155551212). HomePilot's single-DID policy rejects inbound calls to any other number.",
            ),
            SetupStep(
                "4. Point the provider webhook at HomePilot",
                "Provider console → your number → 'A CALL COMES IN' / 'Inbound Webhook' → https://<your-host>/mcp/voip/webhook (HTTP POST). Twilio signs with HMAC-SHA1 using your Auth Token; Telnyx with HMAC-SHA256 using the webhook secret.",
            ),
            SetupStep(
                "5. Create a DID → persona route",
                "After install, call hp.voip.did_route.upsert with your DID + the persona_id that should answer (e.g. 'secretary'). You can also set allow_source_cidrs to restrict to provider IP ranges.",
                link_label="Twilio IP ranges",
                link_url="https://www.twilio.com/docs/voice/webhooks#ip-address-whitelist",
            ),
            SetupStep(
                "6. Enable + Test",
                "Flip TELEPHONY_ENABLED=true and WRITE_ENABLED=true, Save, then Test. A green result means webhook signatures verify and the ingress bridge can open voice_call sessions. Dial your DID — the persona picks up.",
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
