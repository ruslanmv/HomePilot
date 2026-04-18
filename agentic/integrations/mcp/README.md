# HomePilot MCP Communications Servers

This folder contains additive communication MCP servers for:

- WhatsApp (`agentic/integrations/mcp/whatsapp`)
- Telegram (`agentic/integrations/mcp/telegram`)
- VoIP (`agentic/integrations/mcp/voip`)

They are designed to be **installed, enabled, disabled, and uninstalled independently** without breaking core HomePilot chat/voice functionality.

## Industry best-practice posture implemented

- **Safe by default**: `WRITE_ENABLED=false`, `DRY_RUN=true`, `INSTALL_STATE=INSTALLED_DISABLED`.
- **Additive lifecycle states**: `NOT_INSTALLED`, `INSTALLED_DISABLED`, `ENABLED`, `DEGRADED`, `DISABLED`, `UNINSTALLED` (enforced through `INSTALL_STATE`).
- **Persona policy gate**: optional persona allowlists at tool invocation time.
- **Idempotency support**: dedupe keys for outbound sends/calls.
- **Consent checks**: outbound comms require explicit `consent_granted=true`.
- **Audit trail hooks**: in-memory audit event streams per server process.
- **Single-DID app mode (VoIP)**: `VOIP_APP_DID` can enforce one phone number per app instance.

> Note: current scaffolds use in-memory state and placeholder provider actions. Production deployments should back routes/audit/idempotency with durable storage and provider-signed webhook verification.

## Quick start

### 1) Install dependencies

```bash
make -C agentic/integrations/mcp/whatsapp install
make -C agentic/integrations/mcp/telegram install
make -C agentic/integrations/mcp/voip install
```

### 2) Run servers

```bash
make -C agentic/integrations/mcp/whatsapp run
make -C agentic/integrations/mcp/telegram run
make -C agentic/integrations/mcp/voip run
```

Default ports:

- WhatsApp: `9130`
- Telegram: `9131`
- VoIP: `9132`

### 3) Validate behavior

```bash
make -C agentic/integrations/mcp/whatsapp test
make -C agentic/integrations/mcp/telegram test
make -C agentic/integrations/mcp/voip test
```

## Registration model (gateway)

These servers are intended to be registered independently with your MCP gateway (for example, via HomePilot `POST /api/servers`). Persona tool availability should then be managed through persona policy + allowlists.

## Per-server docs

- [WhatsApp README](./whatsapp/README.md)
- [Telegram README](./telegram/README.md)
- [VoIP README](./voip/README.md)
- [Persona integration guide](./PERSONA_INTEGRATION_GUIDE.md)
