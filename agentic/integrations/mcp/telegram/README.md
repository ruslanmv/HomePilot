# HomePilot MCP — Telegram

Additive MCP server for Telegram bot workflows (outbound messages, polling updates, voice note sends, webhook normalization, and lifecycle status).

## Tool manifest

- `hp.telegram.send_message` (write-gated, consent + idempotency aware)
- `hp.telegram.updates.get`
- `hp.telegram.voice_note.send` (write-gated)
- `hp.telegram.webhook.receive`
- `hp.telegram.server.status`

## Environment variables

Start from `.env.example`.

- `WRITE_ENABLED` (default `false`)
- `DRY_RUN` (default `true`)
- `INSTALL_STATE` (default `INSTALLED_DISABLED`)
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET`
- `TELEGRAM_API_BASE`
- `TELEGRAM_PERSONA_ALLOWLIST` (JSON object; optional)

## Installation

```bash
cd agentic/integrations/mcp/telegram
make install
```

## Run

```bash
make run
```

Default port: `9131`

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
    "name":"hp.telegram.send_message",
    "arguments":{
      "chat_id":"123456789",
      "text":"Reminder: daily report is ready.",
      "persona_id":"secretary",
      "consent_granted":true,
      "idempotency_key":"daily-report-2026-04-18"
    }
  }
}
```

Webhook receive:

```json
{
  "jsonrpc":"2.0",
  "id":"3",
  "method":"tools/call",
  "params":{
    "name":"hp.telegram.webhook.receive",
    "arguments":{
      "chat_id":"123456789",
      "text":"please snooze",
      "update_id":"987654321"
    }
  }
}
```

## Install/uninstall guidance

- Register this server independently in the gateway.
- On uninstall: remove registration, revoke bot token/webhook secret, disable Telegram-dependent jobs, keep immutable audit records in your long-term audit sink.

## Best-practice notes

- Keep tool access persona-scoped.
- Favor webhook mode for reliability; keep `updates.get` as polling fallback.
- Move in-memory dedupe/audit structures to durable storage for production.
