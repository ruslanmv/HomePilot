# HomePilot MCP — VoIP

Additive MCP server for outbound voice workflows and single-DID inbound routing support.

## Tool manifest

- `hp.voip.call.create` (write-gated, consent + idempotency aware)
- `hp.voip.call.status`
- `hp.voip.call.end` (write-gated)
- `hp.voip.call.play_tts` (write-gated)
- `hp.voip.call.collect_ack`
- `hp.voip.did_route.upsert` (write-gated)
- `hp.voip.did_route.get`
- `hp.voip.did_route.delete` (write-gated)
- `hp.voip.ingress.route_call` (requires `TELEPHONY_ENABLED=true`)
- `hp.voip.server.status`
- `hp.voip.audit.list`

## Environment variables

Start from `.env.example`.

- `WRITE_ENABLED` (default `false`)
- `DRY_RUN` (default `true`)
- `INSTALL_STATE` (default `INSTALLED_DISABLED`)
- `TELEPHONY_ENABLED` (default `false`)
- `TELEPHONY_PROVIDER` (default `twilio`)
- `VOIP_APP_DID` (optional: enforce single app-level DID)
- `VOIP_PROVIDER`
- `VOIP_API_BASE`
- `VOIP_API_KEY`
- `VOIP_WEBHOOK_SECRET`
- `VOIP_DEFAULT_FROM`
- `VOIP_PERSONA_ALLOWLIST` (JSON object; optional)

## Installation

```bash
cd agentic/integrations/mcp/voip
make install
```

## Run

```bash
make run
```

Default port: `9132`

## Test

```bash
make test
```

## Usage (JSON-RPC examples)

Create outbound call:

```json
{
  "jsonrpc":"2.0",
  "id":"1",
  "method":"tools/call",
  "params":{
    "name":"hp.voip.call.create",
    "arguments":{
      "to":"+15551230000",
      "from":"+15557654321",
      "prompt":"Alert: temperature threshold exceeded.",
      "persona_id":"secretary",
      "consent_granted":true,
      "idempotency_key":"incident-call-2026-04-18-001"
    }
  }
}
```

Upsert DID route:

```json
{
  "jsonrpc":"2.0",
  "id":"2",
  "method":"tools/call",
  "params":{
    "name":"hp.voip.did_route.upsert",
    "arguments":{
      "did_e164":"+15557654321",
      "persona_id":"secretary",
      "allow_source_cidrs":["54.172.60.0/23"],
      "enabled":true
    }
  }
}
```

Route inbound call (telephony adapter side):

```json
{
  "jsonrpc":"2.0",
  "id":"3",
  "method":"tools/call",
  "params":{
    "name":"hp.voip.ingress.route_call",
    "arguments":{
      "to_did_e164":"+15557654321",
      "from_number":"+15559870000",
      "source_ip":"54.172.60.12",
      "provider_call_id":"CA123"
    }
  }
}
```

## Install/uninstall guidance

- Keep VoIP optional and independently registered.
- On uninstall: deregister server, revoke telephony secrets, disable call/escalation jobs, keep historical audit logs in durable storage.

## Best-practice notes

- Use programmable providers (Twilio/Telnyx/Vonage/etc.) for inbound DID routing.
- Verify webhook signatures and apply source IP controls at edge + application layers.
- Persist DID routes, idempotency keys, and audit entries in a database for production.
