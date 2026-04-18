"""MCP server: whatsapp — send messages, check status, list templates.

Production posture:
- Write actions are gated by WRITE_ENABLED.
- DRY_RUN defaults to true for safety.
- Real provider APIs can be wired behind these handlers without changing
  the HomePilot MCP tool contract.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Dict, List

from agentic.integrations.mcp._common.server import Json, ToolDef, create_mcp_app

WRITE_ENABLED = os.getenv("WRITE_ENABLED", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
DEFAULT_FROM = os.getenv("WHATSAPP_DEFAULT_FROM", "").strip()
INSTALL_STATE = os.getenv("INSTALL_STATE", "INSTALLED_DISABLED").strip().upper()
PERSONA_ALLOWLIST = json.loads(
    os.getenv("WHATSAPP_PERSONA_ALLOWLIST", '{"secretary": true, "analyst": false}')
)
# WhatsApp Cloud API signs webhooks with HMAC-SHA256 using the App Secret,
# sent as ``X-Hub-Signature-256: sha256=<hex>``. The orchestrator's
# webhook handler calls ``hp.whatsapp.webhook.verify`` with the raw
# request body + header value to filter spoofed callbacks at the edge.
WEBHOOK_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "").strip()
_AUDIT_EVENTS: List[Json] = []
_OUTBOUND_BY_IDEMPOTENCY: Dict[str, Json] = {}


def _text(text: str) -> Json:
    return {"content": [{"type": "text", "text": text}]}


def _write_gate(action: str) -> Json | None:
    if not WRITE_ENABLED:
        msg = f"Write disabled: '{action}' requires WRITE_ENABLED=true."
        if DRY_RUN:
            msg += " (DRY_RUN mode — no message sent)"
        return _text(msg)
    return None


def _state_gate(action: str) -> Json | None:
    if INSTALL_STATE == "ENABLED":
        return None
    if INSTALL_STATE == "DEGRADED":
        return _text(f"Server state is DEGRADED. '{action}' temporarily unavailable.")
    return _text(f"Server state is {INSTALL_STATE}. '{action}' unavailable until ENABLED.")


def _policy_gate(action: str, args: Json) -> Json | None:
    persona_id = str(args.get("persona_id", "")).strip()
    if not persona_id:
        return None
    if bool(PERSONA_ALLOWLIST.get(persona_id, False)):
        return None
    return _text(f"Policy denied for persona '{persona_id}' on action '{action}'.")


def _audit(event: Json) -> None:
    _AUDIT_EVENTS.append(event)
    if len(_AUDIT_EVENTS) > 500:
        del _AUDIT_EVENTS[:100]


async def whatsapp_send_message(args: Json) -> Json:
    state = _state_gate("whatsapp.send_message")
    if state:
        return state
    gate = _write_gate("whatsapp.send_message")
    if gate:
        return gate
    policy = _policy_gate("whatsapp.send_message", args)
    if policy:
        return policy
    to = str(args.get("to", "")).strip()
    text = str(args.get("text", "")).strip()
    from_id = str(args.get("from", DEFAULT_FROM)).strip()
    consent = bool(args.get("consent_granted", False))
    idempotency_key = str(args.get("idempotency_key", "")).strip()
    if not to or not text:
        return _text("Please provide 'to' and 'text'.")
    if not consent:
        return _text("Outbound WhatsApp blocked: set 'consent_granted=true' for recipient consent.")
    if idempotency_key and idempotency_key in _OUTBOUND_BY_IDEMPOTENCY:
        return {
            "content": [{"type": "text", "text": "Duplicate message suppressed by idempotency key."}],
            "message": _OUTBOUND_BY_IDEMPOTENCY[idempotency_key],
        }
    msg = {
        "to": to,
        "from": from_id or "<default>",
        "text_preview": text[:120],
        "status": "queued",
        "idempotency_key": idempotency_key or None,
    }
    if idempotency_key:
        _OUTBOUND_BY_IDEMPOTENCY[idempotency_key] = msg
    _audit({"action": "send_message", "to": to, "persona_id": args.get("persona_id"), "channel": "whatsapp"})
    return {
        "content": [
            {
                "type": "text",
                "text": f"WhatsApp message queued to {to} from {from_id or '<default>'}: '{text[:120]}' (placeholder).",
            }
        ],
        "message": msg,
    }


async def whatsapp_message_status(args: Json) -> Json:
    state = _state_gate("whatsapp.message_status")
    if state:
        return state
    provider_message_id = str(args.get("provider_message_id", "")).strip()
    if not provider_message_id:
        return _text("Please provide 'provider_message_id'.")
    return _text(f"WhatsApp message status for '{provider_message_id}' is 'queued' (placeholder).")


async def whatsapp_list_templates(args: Json) -> Json:
    state = _state_gate("whatsapp.templates.list")
    if state:
        return state
    locale = str(args.get("locale", "en")).strip() or "en"
    return _text(
        "WhatsApp templates (placeholder): "
        f"[{locale}] incident_alert_v1, recurring_check_ok_v1, escalation_call_v1"
    )


async def whatsapp_receive_webhook(args: Json) -> Json:
    state = _state_gate("whatsapp.webhook.receive")
    if state:
        return state
    from_number = str(args.get("from", "")).strip()
    text = str(args.get("text", "")).strip()
    provider_message_id = str(args.get("provider_message_id", "")).strip()
    normalized = text.upper()
    ack_action = "none"
    if normalized in {"ACK", "SNOOZE", "ESCALATE"}:
        ack_action = normalized.lower()
    _audit(
        {
            "action": "receive_webhook",
            "channel": "whatsapp",
            "from": from_number,
            "provider_message_id": provider_message_id,
            "ack_action": ack_action,
        }
    )
    return {
        "content": [{"type": "text", "text": f"Webhook accepted for sender '{from_number or 'unknown'}'."}],
        "webhook": {
            "from": from_number,
            "provider_message_id": provider_message_id,
            "ack_action": ack_action,
        },
    }


async def whatsapp_webhook_verify(args: Json) -> Json:
    """Verify X-Hub-Signature-256 against the raw webhook body using the
    Meta App Secret. Accepts a per-call ``secret`` override for tests or
    multi-tenant setups where each tenant has its own app.
    """
    state = _state_gate("whatsapp.webhook.verify")
    if state:
        return state
    payload = str(args.get("payload", ""))
    header = str(args.get("signature", "")).strip()
    secret = str(args.get("secret", "")).strip() or WEBHOOK_APP_SECRET
    if not secret:
        return {
            "content": [{"type": "text", "text": "No WHATSAPP_APP_SECRET configured; verification skipped."}],
            "verified": False,
            "reason": "no_secret",
        }
    if not header:
        return {
            "content": [{"type": "text", "text": "Missing X-Hub-Signature-256 header."}],
            "verified": False,
            "reason": "missing_signature",
        }
    computed = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    expected = header.split("=", 1)[1] if "=" in header else header
    verified = hmac.compare_digest(computed, expected.lower())
    _audit({"action": "webhook_verify", "channel": "whatsapp", "verified": verified})
    return {
        "content": [{"type": "text", "text": f"Webhook verify: {'ok' if verified else 'failed'}."}],
        "verified": verified,
        "algorithm": "sha256",
    }


async def whatsapp_server_status(_: Json) -> Json:
    return {
        "content": [{"type": "text", "text": f"Server install_state={INSTALL_STATE}"}],
        "server": {
            "channel": "whatsapp",
            "install_state": INSTALL_STATE,
            "write_enabled": WRITE_ENABLED,
            "dry_run": DRY_RUN,
            "audit_events": len(_AUDIT_EVENTS),
        },
    }


async def whatsapp_audit_list(args: Json) -> Json:
    limit = max(1, min(int(args.get("limit", 20) or 20), 200))
    return {
        "content": [{"type": "text", "text": f"Returning {min(limit, len(_AUDIT_EVENTS))} audit events."}],
        "events": _AUDIT_EVENTS[-limit:],
    }


TOOLS: List[ToolDef] = [
    ToolDef(
        name="hp.whatsapp.send_message",
        description="Send a WhatsApp message. Write-gated.",
        input_schema={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient in E.164 format"},
                "text": {"type": "string"},
                "from": {"type": "string", "description": "Optional sender id/number"},
                "persona_id": {"type": "string", "description": "Persona performing the action"},
                "consent_granted": {"type": "boolean", "default": False},
                "idempotency_key": {"type": "string", "description": "Optional dedupe key for retries"},
                "metadata": {"type": "object", "additionalProperties": True},
            },
            "required": ["to", "text"],
        },
        handler=whatsapp_send_message,
    ),
    ToolDef(
        name="hp.whatsapp.message_status",
        description="Check provider delivery status for a WhatsApp message.",
        input_schema={
            "type": "object",
            "properties": {
                "provider_message_id": {"type": "string"},
            },
            "required": ["provider_message_id"],
        },
        handler=whatsapp_message_status,
    ),
    ToolDef(
        name="hp.whatsapp.templates.list",
        description="List WhatsApp templates by locale.",
        input_schema={
            "type": "object",
            "properties": {
                "locale": {"type": "string", "default": "en"},
            },
        },
        handler=whatsapp_list_templates,
    ),
    ToolDef(
        name="hp.whatsapp.webhook.receive",
        description="Receive inbound WhatsApp webhook payload and detect ACK/SNOOZE/ESCALATE intents.",
        input_schema={
            "type": "object",
            "properties": {
                "from": {"type": "string"},
                "text": {"type": "string"},
                "provider_message_id": {"type": "string"},
                "received_at": {"type": "string"},
            },
        },
        handler=whatsapp_receive_webhook,
    ),
    ToolDef(
        name="hp.whatsapp.webhook.verify",
        description="Verify X-Hub-Signature-256 against raw webhook body using the Meta App Secret.",
        input_schema={
            "type": "object",
            "properties": {
                "payload": {"type": "string", "description": "Raw request body (exact bytes)"},
                "signature": {"type": "string", "description": "Value of X-Hub-Signature-256 header"},
                "secret": {"type": "string", "description": "Override of WHATSAPP_APP_SECRET"},
            },
            "required": ["payload", "signature"],
        },
        handler=whatsapp_webhook_verify,
    ),
    ToolDef(
        name="hp.whatsapp.server.status",
        description="Return install state and server safety mode.",
        input_schema={"type": "object", "properties": {}},
        handler=whatsapp_server_status,
    ),
    ToolDef(
        name="hp.whatsapp.audit.list",
        description="List recent immutable-style audit entries for this server process.",
        input_schema={
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 200}},
        },
        handler=whatsapp_audit_list,
    ),
]

app = create_mcp_app(server_name="homepilot-whatsapp", tools=TOOLS)
