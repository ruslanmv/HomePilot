# INTEGRATIONS

**How to connect HomePilot to Gmail, Outlook, WhatsApp, Slack, and any external service.**

<p align="center">
  <img src="https://img.shields.io/badge/Protocol-MCP-blue?style=for-the-badge" alt="MCP" />
  <img src="https://img.shields.io/badge/Gateway-Context_Forge-orange?style=for-the-badge" alt="Context Forge" />
  <img src="https://img.shields.io/badge/Safety-Ask_Before_Acting-green?style=for-the-badge" alt="Safety" />
</p>

---

## How Integrations Work

HomePilot uses the **MCP (Model Context Protocol)** standard to connect Personas to external tools and services. MCP is the open protocol for exposing tools to AI assistants — think of it as USB for AI.

```
User  →  Persona  →  Backend  →  MCP Gateway (:4444)  →  Tool Server  →  External Service
                                        │
                          ┌─────────────┼─────────────┐
                          │             │             │
                    Built-in       Third-party     Custom
                    Servers        Providers       Servers
                   (9101-9105)   (Zapier, etc.)  (your own)
```

Every integration follows the same pattern:

1. A **tool server** exposes actions via the MCP protocol
2. The server registers with HomePilot's **MCP Gateway** (powered by Context Forge)
3. Personas in **Linked mode** automatically discover and can invoke those actions
4. The **safety policy** controls whether the Persona acts autonomously or asks first

---

## Built-in Tool Servers

These ship with HomePilot and launch automatically with `make start`:

| Server | Port | Actions |
| :--- | :--- | :--- |
| **Personal Assistant** | 9101 | Create tasks, set reminders, manage schedules |
| **Knowledge** | 9102 | Search documents, RAG queries, knowledge base lookups |
| **Decision Copilot** | 9103 | Pro/con analysis, decision matrices, risk assessment |
| **Executive Briefing** | 9104 | Daily digests, status summaries, report generation |
| **Web Search** | 9105 | Real-time web search (SearXNG for home, Tavily for enterprise) |

**A2A Agents** (Agent-to-Agent) handle multi-step coordination:

| Agent | Port | Role |
| :--- | :--- | :--- |
| **Everyday Assistant** | 9201 | General-purpose multi-step task execution |
| **Chief of Staff** | 9202 | Prioritization, delegation, executive coordination |

These require no configuration. They start with the platform.

---

## Adding External Integrations

### Option 1: Third-Party MCP Providers (Fastest)

Several providers offer ready-made MCP endpoints that you can connect to HomePilot without writing code.

#### Zapier MCP

Zapier offers managed MCP endpoints for 7,000+ apps.

| Integration | Status | Actions |
| :--- | :--- | :--- |
| **Gmail** | Available | Read, send, draft, archive, label, search emails |
| **Outlook Mail** | Available | Read, send, manage messages via Microsoft Graph |
| **WhatsApp** | Available | Send messages via WhatsApp Business API |
| **SMS** | Available | Send SMS via Twilio or similar |
| **Google Calendar** | Available | Create events, check availability, send invites |
| **Slack** | Available | Post messages, read channels, manage threads |
| **GitHub** | Available | Create issues, review PRs, manage repos |
| **Notion** | Available | Create pages, update databases, search |
| **Trello** | Available | Create cards, move between lists, assign |
| **Google Sheets** | Available | Read, write, update spreadsheets |

**Setup:**

1. Create a Zapier account and navigate to MCP settings
2. Authorize the services you want (Gmail, Outlook, etc.)
3. Copy the MCP endpoint URL
4. Register with HomePilot:

```bash
curl -X POST http://localhost:4444/api/servers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "zapier-gmail",
    "url": "https://actions.zapier.com/mcp/YOUR_ENDPOINT_ID",
    "description": "Gmail via Zapier MCP"
  }'
```

Or use the HomePilot API:

```bash
curl -X POST http://localhost:8000/v1/agentic/register/tool \
  -H "Content-Type: application/json" \
  -d '{
    "name": "zapier-gmail",
    "url": "https://actions.zapier.com/mcp/YOUR_ENDPOINT_ID",
    "description": "Gmail read, send, draft, archive via Zapier",
    "category": "communication"
  }'
```

**Pros:** No servers to host, OAuth handled by Zapier, 7,000+ apps available.
**Cons:** Requires Zapier plan (task quotas), not self-hosted.

---

#### KlavisAI MCP

KlavisAI provides a composable suite of MCP servers covering email, calendar, and messaging.

| Integration | Status | Actions |
| :--- | :--- | :--- |
| **Gmail** | Available | Read, send, draft, label, search |
| **Outlook Mail** | Available | Read, send, manage via Microsoft Graph |
| **Outlook Calendar** | Available | Events, scheduling, availability |
| **Google Calendar** | Available | Events, invites, availability |
| **WhatsApp Business** | Available | Send messages via official Business API |
| **Google Drive** | Available | Search, read, upload files |

**Setup:**

1. Create a KlavisAI account
2. Configure OAuth for each service (Google, Microsoft, WhatsApp Business)
3. Get your MCP server URLs
4. Register each server:

```bash
# Gmail
curl -X POST http://localhost:4444/api/servers \
  -H "Content-Type: application/json" \
  -d '{"name": "klavis-gmail", "url": "https://api.klavis.ai/mcp/gmail/YOUR_KEY", "description": "Gmail via KlavisAI"}'

# Outlook
curl -X POST http://localhost:4444/api/servers \
  -H "Content-Type: application/json" \
  -d '{"name": "klavis-outlook", "url": "https://api.klavis.ai/mcp/outlook/YOUR_KEY", "description": "Outlook via KlavisAI"}'

# WhatsApp
curl -X POST http://localhost:4444/api/servers \
  -H "Content-Type: application/json" \
  -d '{"name": "klavis-whatsapp", "url": "https://api.klavis.ai/mcp/whatsapp/YOUR_KEY", "description": "WhatsApp via KlavisAI"}'
```

**Pros:** Unified platform, developer-friendly, supports Gmail + Outlook + WhatsApp in one service.
**Cons:** Third-party hosted, requires OAuth configuration, evaluate cost and security.

---

#### Infobip MCP

Infobip specializes in multi-channel messaging — ideal if communication is your primary use case.

| Integration | Status | Actions |
| :--- | :--- | :--- |
| **WhatsApp** | Available | Send/receive messages, templates, media |
| **SMS** | Available | Send/receive SMS globally |
| **Viber** | Available | Send messages via Viber Business |
| **Voice** | Available | Outbound calls, IVR, voice messages |
| **Email** | Available | Transactional email via Infobip SMTP |

**Setup:**

1. Create an Infobip account
2. Get your API key and base URL
3. Register the MCP endpoint:

```bash
curl -X POST http://localhost:4444/api/servers \
  -H "Content-Type: application/json" \
  -d '{"name": "infobip-messaging", "url": "https://YOUR_BASE.api.infobip.com/mcp", "description": "WhatsApp, SMS, Voice via Infobip"}'
```

**Pros:** Enterprise-grade multi-channel messaging, global SMS/voice, WhatsApp templates.
**Cons:** Telecom-focused (less about email/productivity), requires Infobip account.

---

#### viaSocket MCP

viaSocket provides managed MCP servers with a focus on productivity.

| Integration | Status | Actions |
| :--- | :--- | :--- |
| **Gmail** | Available | Full Gmail tool actions via OAuth |
| **Google Sheets** | Available | Read, write, update spreadsheets |
| **Airtable** | Available | CRUD operations on bases |

**Setup:**

```bash
curl -X POST http://localhost:4444/api/servers \
  -H "Content-Type: application/json" \
  -d '{"name": "viasocket-gmail", "url": "https://mcp.viasocket.com/gmail/YOUR_KEY", "description": "Gmail via viaSocket"}'
```

**Pros:** Quick setup for Gmail, managed OAuth.
**Cons:** Narrower service coverage — combine with other providers for Outlook/WhatsApp.

---

### Option 2: Self-Hosted MCP Servers (Full Control)

For maximum control and privacy, you can run your own MCP tool servers. Each server is a lightweight HTTP service that implements the MCP protocol.

#### Email Server (SMTP/IMAP)

A self-hosted server that connects directly to any email account:

```python
# agentic/integrations/mcp/email_server.py
from mcp.server import Server
import smtplib
import imaplib
from email.mime.text import MIMEText

server = Server("email-connector")

@server.tool("send_email")
async def send_email(to: str, subject: str, body: str):
    """Send an email via SMTP."""
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["To"] = to
    msg["From"] = SMTP_FROM
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.send_message(msg)
    return {"status": "sent", "to": to, "subject": subject}

@server.tool("read_inbox")
async def read_inbox(limit: int = 10):
    """Read recent emails from IMAP inbox."""
    with imaplib.IMAP4_SSL(IMAP_HOST) as imap:
        imap.login(IMAP_USER, IMAP_PASS)
        imap.select("INBOX")
        _, messages = imap.search(None, "ALL")
        # ... parse and return recent messages
    return {"emails": emails}
```

Configure via environment variables in `.env`:

```bash
# Email connector
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=465
EMAIL_SMTP_USER=your@gmail.com
EMAIL_SMTP_PASS=your-app-password
EMAIL_IMAP_HOST=imap.gmail.com
EMAIL_IMAP_USER=your@gmail.com
EMAIL_IMAP_PASS=your-app-password
```

#### WhatsApp Server (via Business API)

```python
# agentic/integrations/mcp/whatsapp_server.py
from mcp.server import Server
import httpx

server = Server("whatsapp-connector")

@server.tool("send_whatsapp")
async def send_whatsapp(phone: str, message: str):
    """Send a WhatsApp message via the Business API."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "text",
                "text": {"body": message}
            }
        )
    return resp.json()
```

#### Calendar Server (CalDAV)

```python
# agentic/integrations/mcp/calendar_server.py
from mcp.server import Server
import caldav

server = Server("calendar-connector")

@server.tool("create_event")
async def create_event(title: str, start: str, end: str, description: str = ""):
    """Create a calendar event."""
    client = caldav.DAVClient(url=CALDAV_URL, username=CALDAV_USER, password=CALDAV_PASS)
    calendar = client.principal().calendars()[0]
    event = calendar.save_event(
        dtstart=start, dtend=end, summary=title, description=description
    )
    return {"status": "created", "title": title, "start": start}

@server.tool("check_availability")
async def check_availability(date: str):
    """Check calendar availability for a given date."""
    # ... query calendar and return free/busy slots
    return {"date": date, "slots": free_slots}
```

#### Running Self-Hosted Servers

Add your server to Docker Compose or run standalone:

```bash
# Standalone
cd agentic/integrations/mcp
python email_server.py --port 9201

# Or add to docker-compose
# See agentic/ops/compose/docker-compose.yml for examples
```

Register with the gateway:

```bash
curl -X POST http://localhost:4444/api/servers \
  -H "Content-Type: application/json" \
  -d '{"name": "email", "url": "http://localhost:9201", "description": "Self-hosted email (SMTP/IMAP)"}'
```

---

### Option 3: Hybrid Approach (Recommended)

The most practical setup combines self-hosted and third-party servers:

| Service | Recommended Provider | Why |
| :--- | :--- | :--- |
| **Gmail** | Zapier MCP or self-hosted SMTP/IMAP | Zapier for speed, self-hosted for privacy |
| **Outlook** | KlavisAI or Zapier | Best Microsoft Graph integration |
| **WhatsApp** | KlavisAI or Infobip | Official Business API support |
| **Calendar** | Zapier (Google) or self-hosted CalDAV | Depends on your calendar provider |
| **Slack** | Zapier | Fastest setup, full channel access |
| **GitHub** | Zapier or self-hosted | gh CLI wrapper is also viable |
| **SMS** | Infobip | Best global SMS coverage |
| **Home Automation** | Self-hosted | Direct local network access needed |
| **Database** | Self-hosted | Must connect to your local DB |

---

## Provider Comparison

| | Zapier | KlavisAI | Infobip | viaSocket | Self-hosted |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Gmail** | Yes | Yes | Email (basic) | Yes | Yes |
| **Outlook** | Yes | Yes | No | No | Yes (IMAP) |
| **WhatsApp** | Yes | Yes | Yes | No | Yes (Business API) |
| **Calendar** | Yes | Yes | No | No | Yes (CalDAV) |
| **Slack** | Yes | No | No | No | Yes (API) |
| **GitHub** | Yes | No | No | No | Yes (API) |
| **SMS** | Yes | No | Yes | No | Yes (Twilio) |
| **Voice/Calls** | No | No | Yes | No | Custom |
| **Setup effort** | Low | Low | Medium | Low | High |
| **Privacy** | Third-party | Third-party | Third-party | Third-party | Full control |
| **Cost** | Per-task | Per-use | Per-message | Per-use | Infrastructure |
| **Self-hosted** | No | No | No | No | Yes |

---

## Registration API Reference

### Register via MCP Gateway (direct)

```bash
POST http://localhost:4444/api/servers

{
  "name": "server-name",
  "url": "http://server-host:port",
  "description": "What this server does"
}
```

### Register via HomePilot API

```bash
# Register a tool server
POST http://localhost:8000/v1/agentic/register/tool
{
  "name": "my-integration",
  "url": "http://localhost:9300",
  "description": "Custom integration",
  "category": "communication"
}

# Register an A2A agent
POST http://localhost:8000/v1/agentic/register/agent
{
  "name": "my-agent",
  "url": "http://localhost:9400",
  "description": "Custom A2A agent"
}

# Register a gateway
POST http://localhost:8000/v1/agentic/register/gateway
{
  "name": "my-gateway",
  "url": "http://gateway-host:port",
  "description": "Additional MCP gateway"
}
```

### Verify Registration

```bash
# List all registered capabilities
GET http://localhost:8000/v1/agentic/capabilities

# Browse the full catalog
GET http://localhost:8000/v1/agentic/catalog

# Check status
GET http://localhost:8000/v1/agentic/status
```

---

## Safety & Policy Configuration

Every integration operates under HomePilot's **ask-before-acting** safety model.

### Autonomy Levels

| Level | Behavior | Use For |
| :--- | :--- | :--- |
| **0 — Read-only** | Can search, query, and read. Cannot modify or send. | Calendar checks, email search, status queries |
| **1 — Confirm** (default) | Describes the intended action, waits for user approval | Sending emails, posting messages, creating events |
| **2 — Autonomous** | Acts within configured boundaries without asking | Low-risk automations, routine tasks |

### Configuring Policy

Set the autonomy level per tool:

```bash
# Set Gmail to confirm-before-send (default)
curl -X PATCH http://localhost:8000/v1/agentic/policy \
  -H "Content-Type: application/json" \
  -d '{"tool": "zapier-gmail", "level": 1}'

# Set calendar reads to autonomous
curl -X PATCH http://localhost:8000/v1/agentic/policy \
  -H "Content-Type: application/json" \
  -d '{"tool": "klavis-calendar", "level": 0, "actions": ["check_availability", "list_events"]}'
```

### Per-Persona Overrides

Different Personas can have different autonomy levels:

- A "Secretary" Persona might have Level 2 for calendar but Level 1 for email
- A "Kids Assistant" Persona might have Level 0 (read-only) for everything
- A "Chief of Staff" Persona might have Level 2 for Slack and GitHub

---

## Step-by-Step: Connect Gmail in 5 Minutes

The fastest path to a working email integration:

### 1. Choose a provider

For this example, we use **Zapier MCP** (no code required).

### 2. Create Zapier MCP endpoint

1. Go to Zapier → Settings → MCP
2. Click "Add Connection" → Gmail
3. Authorize your Google account
4. Copy the MCP endpoint URL

### 3. Register with HomePilot

```bash
curl -X POST http://localhost:4444/api/servers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "gmail",
    "url": "https://actions.zapier.com/mcp/YOUR_ENDPOINT",
    "description": "Gmail: read, send, draft, archive"
  }'
```

### 4. Verify it works

```bash
curl http://localhost:8000/v1/agentic/capabilities | python -m json.tool
```

You should see Gmail actions in the capability list.

### 5. Use it with a Persona

Open Voice Mode, select a Persona in Linked mode, and say:

> *"Check my inbox for any emails from the design team"*

The Persona will:
1. Discover the Gmail tool
2. Describe the action: "I'll search your Gmail for emails from the design team"
3. Wait for your confirmation (Level 1)
4. Execute and report the results

---

## Step-by-Step: Connect WhatsApp

### Using KlavisAI

1. Create KlavisAI account
2. Link your WhatsApp Business account
3. Get your MCP server URL
4. Register:

```bash
curl -X POST http://localhost:4444/api/servers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "whatsapp",
    "url": "https://api.klavis.ai/mcp/whatsapp/YOUR_KEY",
    "description": "WhatsApp: send and receive messages"
  }'
```

### Using Infobip

1. Create Infobip account
2. Set up WhatsApp Business channel
3. Get API credentials
4. Register:

```bash
curl -X POST http://localhost:4444/api/servers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "infobip-whatsapp",
    "url": "https://YOUR_BASE.api.infobip.com/mcp",
    "description": "WhatsApp, SMS, Voice via Infobip"
  }'
```

### Test it

> *"Send a WhatsApp message to John: I'll be there in 10 minutes"*

---

## Building a Custom MCP Tool Server

If none of the providers cover your use case, build your own.

### Minimal Template

```python
#!/usr/bin/env python3
"""Custom MCP tool server template for HomePilot."""

from mcp.server import Server
from mcp.server.stdio import stdio_server
import asyncio

server = Server("my-custom-tool")

@server.tool("my_action")
async def my_action(param1: str, param2: str = "default"):
    """Describe what this action does — the Persona reads this description."""
    # Your logic here
    result = do_something(param1, param2)
    return {"status": "success", "data": result}

@server.tool("my_query")
async def my_query(query: str):
    """Search or read something — safe for Level 0 autonomy."""
    results = search(query)
    return {"results": results}

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write)

if __name__ == "__main__":
    asyncio.run(main())
```

### Run it

```bash
python my_custom_tool.py --port 9300
```

### Register it

```bash
curl -X POST http://localhost:4444/api/servers \
  -H "Content-Type: application/json" \
  -d '{"name": "my-custom-tool", "url": "http://localhost:9300", "description": "My custom integration"}'
```

Every Persona in Linked mode will now automatically discover and can use your tool.

---

## FAQ

**Do I need to configure each Persona separately for integrations?**
No. Once a tool server is registered with the MCP gateway, every Persona in Linked mode discovers it automatically.

**What if a third-party provider goes down?**
HomePilot's capability discovery is dynamic. If a server is unreachable, it is simply excluded from the available tools. The Persona continues working with remaining tools.

**Can I use multiple providers for the same service?**
Yes. You can register both a Zapier Gmail server and a self-hosted SMTP server. The Persona can use either.

**Is my data sent to third-party providers?**
Only if you register a third-party MCP server (Zapier, KlavisAI, etc.). Self-hosted servers keep everything local. The MCP gateway itself runs on your machine.

**Can I restrict which Personas can use which tools?**
Yes, through the policy system. Set per-Persona or per-tool autonomy levels.

**How do I remove an integration?**
Deregister the server from the gateway. It will no longer appear in capability discovery.

---

<p align="center">
  <b>HomePilot Integrations</b> — Connect your Persona to the real world.<br>
  <a href="PERSONA.md">Persona Spec</a> · <a href="BLOG.md">Product Overview</a> · <a href="../README.md">README</a>
</p>
