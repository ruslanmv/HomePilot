# HomePilot MCP Comms — Persona Integration Guide (Next Development Plan)

This guide defines a simple implementation plan for integrating WhatsApp, Telegram, and VoIP MCP servers with HomePilot personas in a safe, additive way.

## Goals

1. Keep comms channels optional (install/uninstall without core regressions).
2. Enforce persona-scoped permissions for each channel/tool.
3. Support a single app-level DID in phase 1.
4. Enable proactive outbound escalation workflows (chat → call).

## Reference architecture

```text
Scheduler / Trigger Engine
        ↓
Persona Policy Engine (allowlist + rate limits + consent)
        ↓
Channel Orchestrator
   ├─ WhatsApp MCP
   ├─ Telegram MCP
   └─ VoIP MCP
        ↓
Audit / Metrics / Incident Timeline
```

## Phase plan

### Phase 1 — Baseline registration and persona allowlists

- Register each MCP server independently in the gateway.
- Keep each server in `INSTALL_STATE=INSTALLED_DISABLED` until validated.
- Define `persona_channel_policy` with minimum fields:
  - `persona_id`
  - `channel` (`whatsapp|telegram|voip`)
  - `enabled`
  - `allowed_tools[]`
  - `max_actions_per_hour`
- Start with defaults:
  - `secretary`: WhatsApp + Telegram + VoIP outbound
  - `analyst`: read-only/no outbound comms

### Phase 2 — Outbound proactive workflows

- Add recurrent checks (cron/job system) that emit incidents.
- Route incidents through channel orchestration strategy:
  1. send WhatsApp message
  2. fallback Telegram message
  3. escalate to VoIP call
- Require:
  - `consent_granted=true`
  - `idempotency_key`
  - audit event with incident id + persona id

### Phase 3 — Inbound routing and acknowledgment loop

- VoIP:
  - enforce `VOIP_APP_DID` single-number policy
  - upsert DID→persona route
  - use source CIDR allowlist on ingress
- WhatsApp/Telegram:
  - webhook receive tools normalize ACK/SNOOZE/ESCALATE responses
- Persist user acknowledgment in incident timeline and update retry policy.

### Phase 4 — Hardening for production

- Replace in-memory audit/idempotency/route structures with DB-backed stores.
- Add provider webhook signature verification.
- Add dead-letter queue + retries with exponential backoff.
- Add compliance retention windows and data deletion controls.

## Minimal data model to add in HomePilot backend

- `persona_channel_policy`
- `contact_endpoints`
- `incident_runs`
- `channel_delivery_attempts`
- `channel_ack_events`

## Operational checklist

- [ ] Server install/run/test validated in CI.
- [ ] Persona policy gate enforced server-side (not UI-only).
- [ ] Consent and quiet-hours policy enabled.
- [ ] Idempotency key required for outbound mutating actions.
- [ ] Audit events exported to centralized immutable sink.
- [ ] Uninstall runbook documented (deregister, revoke secrets, disable jobs).

