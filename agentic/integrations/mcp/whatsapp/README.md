# HomePilot MCP — WhatsApp

Additive MCP server for WhatsApp messaging workflows (send, status, templates, inbound webhook normalization, and lightweight audit visibility).

## Tool manifest

- `hp.whatsapp.send_message` (write-gated, consent + idempotency aware)
- `hp.whatsapp.message_status`
- `hp.whatsapp.templates.list`
- `hp.whatsapp.webhook.receive`
- `hp.whatsapp.server.status`
- `hp.whatsapp.audit.list`

## Environment variables

Start from `.env.example`.

- `WRITE_ENABLED` (default `false`)
- `DRY_RUN` (default `true`)
- `INSTALL_STATE` (default `INSTALLED_DISABLED`)
- `WHATSAPP_DEFAULT_FROM`
- `WHATSAPP_PROVIDER`
- `WHATSAPP_API_BASE`
- `WHATSAPP_API_KEY`
- `WHATSAPP_WEBHOOK_SECRET`
- `WHATSAPP_PERSONA_ALLOWLIST` (JSON object; optional)

## Installation

```bash
cd agentic/integrations/mcp/whatsapp
make install
```

## Run

```bash
make run
```

Default port: `9130`

## Test

```bash
make test
```

## Usage (JSON-RPC examples)

List tools:

```json
{"jsonrpc":"2.0","id":"1","method":"tools/list"}
```

Send message (requires `INSTALL_STATE=ENABLED`, `WRITE_ENABLED=true`, and consent):

```json
{
  "jsonrpc":"2.0",
  "id":"2",
  "method":"tools/call",
  "params":{
    "name":"hp.whatsapp.send_message",
    "arguments":{
      "to":"+15551234567",
      "text":"Incident detected: check your dashboard.",
      "persona_id":"secretary",
      "consent_granted":true,
      "idempotency_key":"incident-2026-04-18-001"
    }
  }
}
```

Receive webhook payload:

```json
{
  "jsonrpc":"2.0",
  "id":"3",
  "method":"tools/call",
  "params":{
    "name":"hp.whatsapp.webhook.receive",
    "arguments":{
      "from":"+15559876543",
      "text":"ACK",
      "provider_message_id":"wamid.abc123"
    }
  }
}
```

## Install/uninstall guidance

- Keep this server optional in gateway registration.
- On uninstall: deregister server, revoke WhatsApp secrets, disable scheduled jobs depending on WhatsApp delivery, keep audit history in your durable audit backend.

## Best-practice notes

- Use idempotency keys for retries.
- Keep outbound recipient consent explicit and revocable.
- Move `_AUDIT_EVENTS` and idempotency maps to persistent storage in production.
