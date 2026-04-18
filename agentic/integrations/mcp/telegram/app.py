"""MCP server: telegram — send messages, fetch updates, optional voice note send.

Production posture:
- Write actions are gated by WRITE_ENABLED.
- DRY_RUN defaults to true for safety.
"""

from __future__ import annotations

import json
import os
from typing import List

from agentic.integrations.mcp._common.server import Json, ToolDef, create_mcp_app

WRITE_ENABLED = os.getenv("WRITE_ENABLED", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
INSTALL_STATE = os.getenv("INSTALL_STATE", "INSTALLED_DISABLED").strip().upper()
PERSONA_ALLOWLIST = json.loads(
    os.getenv("TELEGRAM_PERSONA_ALLOWLIST", '{"secretary": true, "analyst": false}')
)
_AUDIT_EVENTS: List[Json] = []
_OUTBOUND_BY_KEY: dict[str, Json] = {}


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


async def telegram_send_message(args: Json) -> Json:
    state = _state_gate("telegram.send_message")
    if state:
        return state
    gate = _write_gate("telegram.send_message")
    if gate:
        return gate
    policy = _policy_gate("telegram.send_message", args)
    if policy:
        return policy
    chat_id = str(args.get("chat_id", "")).strip()
    text = str(args.get("text", "")).strip()
    consent = bool(args.get("consent_granted", False))
    idempotency_key = str(args.get("idempotency_key", "")).strip()
    if not chat_id or not text:
        return _text("Please provide 'chat_id' and 'text'.")
    if not consent:
        return _text("Outbound Telegram blocked: set 'consent_granted=true' for recipient consent.")
    if idempotency_key and idempotency_key in _OUTBOUND_BY_KEY:
        return {
            "content": [{"type": "text", "text": "Duplicate message suppressed by idempotency key."}],
            "message": _OUTBOUND_BY_KEY[idempotency_key],
        }
    msg = {
        "chat_id": chat_id,
        "text_preview": text[:120],
        "status": "queued",
        "idempotency_key": idempotency_key or None,
    }
    if idempotency_key:
        _OUTBOUND_BY_KEY[idempotency_key] = msg
    _audit({"action": "send_message", "channel": "telegram", "chat_id": chat_id, "persona_id": args.get("persona_id")})
    return {
        "content": [{"type": "text", "text": f"Telegram message queued to chat_id={chat_id}: '{text[:120]}' (placeholder)."}],
        "message": msg,
    }


async def telegram_get_updates(args: Json) -> Json:
    state = _state_gate("telegram.updates.get")
    if state:
        return state
    limit = max(1, min(int(args.get("limit", 20) or 20), 100))
    return _text(f"Telegram updates fetched (limit={limit}) — placeholder response.")


async def telegram_send_voice_note(args: Json) -> Json:
    state = _state_gate("telegram.voice_note.send")
    if state:
        return state
    gate = _write_gate("telegram.send_voice_note")
    if gate:
        return gate
    policy = _policy_gate("telegram.voice_note.send", args)
    if policy:
        return policy
    chat_id = str(args.get("chat_id", "")).strip()
    media_url = str(args.get("media_url", "")).strip()
    if not chat_id or not media_url:
        return _text("Please provide 'chat_id' and 'media_url'.")
    _audit({"action": "send_voice_note", "channel": "telegram", "chat_id": chat_id, "persona_id": args.get("persona_id")})
    return _text(f"Telegram voice note queued to chat_id={chat_id} from '{media_url}' (placeholder).")


async def telegram_receive_webhook(args: Json) -> Json:
    state = _state_gate("telegram.webhook.receive")
    if state:
        return state
    chat_id = str(args.get("chat_id", "")).strip()
    text = str(args.get("text", "")).strip()
    update_id = str(args.get("update_id", "")).strip()
    _audit({"action": "receive_webhook", "channel": "telegram", "chat_id": chat_id, "update_id": update_id})
    return {
        "content": [{"type": "text", "text": f"Telegram update accepted for chat_id={chat_id or 'unknown'}."}],
        "update": {"chat_id": chat_id, "text": text, "update_id": update_id},
    }


async def telegram_server_status(_: Json) -> Json:
    return {
        "content": [{"type": "text", "text": f"Server install_state={INSTALL_STATE}"}],
        "server": {
            "channel": "telegram",
            "install_state": INSTALL_STATE,
            "write_enabled": WRITE_ENABLED,
            "dry_run": DRY_RUN,
            "audit_events": len(_AUDIT_EVENTS),
        },
    }


TOOLS: List[ToolDef] = [
    ToolDef(
        name="hp.telegram.send_message",
        description="Send a Telegram message. Write-gated.",
        input_schema={
            "type": "object",
            "properties": {
                "chat_id": {"type": "string"},
                "text": {"type": "string"},
                "persona_id": {"type": "string"},
                "consent_granted": {"type": "boolean", "default": False},
                "idempotency_key": {"type": "string", "description": "Optional dedupe key for retries"},
                "parse_mode": {"type": "string", "enum": ["Markdown", "HTML", "None"]},
            },
            "required": ["chat_id", "text"],
        },
        handler=telegram_send_message,
    ),
    ToolDef(
        name="hp.telegram.updates.get",
        description="Fetch Telegram updates (polling fallback).",
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            },
        },
        handler=telegram_get_updates,
    ),
    ToolDef(
        name="hp.telegram.voice_note.send",
        description="Send a Telegram voice note from an accessible media URL. Write-gated.",
        input_schema={
            "type": "object",
            "properties": {
                "chat_id": {"type": "string"},
                "media_url": {"type": "string"},
                "persona_id": {"type": "string"},
                "caption": {"type": "string"},
            },
            "required": ["chat_id", "media_url"],
        },
        handler=telegram_send_voice_note,
    ),
    ToolDef(
        name="hp.telegram.webhook.receive",
        description="Receive Telegram webhook update payload (bot webhook mode).",
        input_schema={
            "type": "object",
            "properties": {
                "chat_id": {"type": "string"},
                "text": {"type": "string"},
                "update_id": {"type": "string"},
                "received_at": {"type": "string"},
            },
        },
        handler=telegram_receive_webhook,
    ),
    ToolDef(
        name="hp.telegram.server.status",
        description="Return install state and server safety mode.",
        input_schema={"type": "object", "properties": {}},
        handler=telegram_server_status,
    ),
]

app = create_mcp_app(server_name="homepilot-telegram", tools=TOOLS)
