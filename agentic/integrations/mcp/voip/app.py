"""MCP server: voip — outbound call orchestration, DID routes, ingress checks.

Production posture:
- Mutating operations are write-gated.
- DRY_RUN defaults to true.
- Provider adapters (Twilio/Telnyx/Infobip/etc.) can be added behind this
  stable tool contract.
- Webhook signature verification exposed via ``hp.voip.webhook.verify``
  so the orchestrator rejects spoofed provider callbacks at the edge.
- Incident trigger (``hp.voip.incident.trigger``) lets recurrent checks
  raise a "secretary calls me" escalation without hardcoding the
  cron surface inside this server.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
from typing import Any, Dict, List

from agentic.integrations.mcp._common.server import Json, ToolDef, create_mcp_app

WRITE_ENABLED = os.getenv("WRITE_ENABLED", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
DEFAULT_FROM = os.getenv("VOIP_DEFAULT_FROM", "").strip()
APP_DID = os.getenv("VOIP_APP_DID", "").strip()
TELEPHONY_ENABLED = os.getenv("TELEPHONY_ENABLED", "false").lower() == "true"
TELEPHONY_PROVIDER = os.getenv("TELEPHONY_PROVIDER", "twilio").strip() or "twilio"
INSTALL_STATE = os.getenv("INSTALL_STATE", "INSTALLED_DISABLED").strip().upper()
PERSONA_ALLOWLIST = json.loads(
    os.getenv("VOIP_PERSONA_ALLOWLIST", '{"secretary": true, "analyst": false}')
)
# Provider webhook secret. When set, ``hp.voip.webhook.verify`` performs
# an HMAC-SHA1 (Twilio) or HMAC-SHA256 (Telnyx/Infobip) comparison and
# rejects spoofed callbacks. Empty = verification disabled (dev only).
WEBHOOK_SECRET = os.getenv("VOIP_WEBHOOK_SECRET", "").strip()

RouteRecord = Dict[str, Any]
_DID_ROUTES: Dict[str, RouteRecord] = {}
_AUDIT_EVENTS: List[Json] = []
_OUTBOUND_CALLS_BY_IDEMPOTENCY: Dict[str, Json] = {}


def _text(text: str) -> Json:
    return {"content": [{"type": "text", "text": text}]}


def _write_gate(action: str) -> Json | None:
    if not WRITE_ENABLED:
        msg = f"Write disabled: '{action}' requires WRITE_ENABLED=true."
        if DRY_RUN:
            msg += " (DRY_RUN mode — no call action performed)"
        return _text(msg)
    return None


def _telephony_gate(action: str) -> Json | None:
    if TELEPHONY_ENABLED:
        return None
    return _text(
        f"Telephony ingress disabled: '{action}' requires TELEPHONY_ENABLED=true. "
        "Core voice-call UX remains unchanged."
    )


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


def _normalize_did(value: str) -> str:
    return value.strip().replace(" ", "")


def _source_ip_allowed(source_ip: str, allow_source_cidrs: List[str]) -> bool:
    if not allow_source_cidrs:
        return True
    try:
        ip = ipaddress.ip_address(source_ip)
    except ValueError:
        return False
    for cidr in allow_source_cidrs:
        try:
            if ip in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


async def voip_create_outbound_call(args: Json) -> Json:
    state = _state_gate("voip.call.create")
    if state:
        return state
    gate = _write_gate("voip.call.create")
    if gate:
        return gate
    policy = _policy_gate("voip.call.create", args)
    if policy:
        return policy
    to = str(args.get("to", "")).strip()
    from_number = str(args.get("from", DEFAULT_FROM)).strip()
    prompt = str(args.get("prompt", "")).strip()
    idempotency_key = str(args.get("idempotency_key", "")).strip()
    consent = bool(args.get("consent_granted", False))
    if not to:
        return _text("Please provide 'to'.")
    if not consent:
        return _text("Outbound call blocked: set 'consent_granted=true' for recipient consent.")
    if idempotency_key and idempotency_key in _OUTBOUND_CALLS_BY_IDEMPOTENCY:
        return {
            "content": [{"type": "text", "text": "Duplicate call request suppressed by idempotency key."}],
            "call": _OUTBOUND_CALLS_BY_IDEMPOTENCY[idempotency_key],
        }
    call = {
        "to": to,
        "from": from_number or "<default>",
        "prompt_preview": prompt[:100],
        "status": "queued",
        "idempotency_key": idempotency_key or None,
    }
    if idempotency_key:
        _OUTBOUND_CALLS_BY_IDEMPOTENCY[idempotency_key] = call
    _audit({"action": "call_create", "channel": "voip", "to": to, "persona_id": args.get("persona_id")})
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Outbound call queued to {to} from {from_number or '<default>'}. "
                    f"Prompt='{prompt[:100]}' (placeholder)."
                ),
            }
        ],
        "call": call,
    }


async def voip_get_call_status(args: Json) -> Json:
    state = _state_gate("voip.call.status")
    if state:
        return state
    call_id = str(args.get("call_id", "")).strip()
    if not call_id:
        return _text("Please provide 'call_id'.")
    return _text(f"Call '{call_id}' status is 'queued' (placeholder).")


async def voip_end_call(args: Json) -> Json:
    state = _state_gate("voip.call.end")
    if state:
        return state
    gate = _write_gate("voip.call.end")
    if gate:
        return gate
    policy = _policy_gate("voip.call.end", args)
    if policy:
        return policy
    call_id = str(args.get("call_id", "")).strip()
    if not call_id:
        return _text("Please provide 'call_id'.")
    return _text(f"Call '{call_id}' terminated (placeholder).")


async def voip_play_tts(args: Json) -> Json:
    state = _state_gate("voip.call.play_tts")
    if state:
        return state
    gate = _write_gate("voip.call.play_tts")
    if gate:
        return gate
    policy = _policy_gate("voip.call.play_tts", args)
    if policy:
        return policy
    call_id = str(args.get("call_id", "")).strip()
    text = str(args.get("text", "")).strip()
    if not call_id or not text:
        return _text("Please provide 'call_id' and 'text'.")
    return _text(f"TTS queued on call '{call_id}' (len={len(text)}) (placeholder).")


async def voip_collect_ack(args: Json) -> Json:
    state = _state_gate("voip.call.collect_ack")
    if state:
        return state
    call_id = str(args.get("call_id", "")).strip()
    signal = str(args.get("signal", "")).strip().lower()
    if not call_id:
        return _text("Please provide 'call_id'.")
    mapping = {
        "1": "ack",
        "2": "snooze",
        "3": "escalate",
        "ack": "ack",
        "snooze": "snooze",
        "escalate": "escalate",
    }
    decision = mapping.get(signal, "unknown")
    _audit({"action": "collect_ack", "channel": "voip", "call_id": call_id, "decision": decision})
    return {
        "content": [{"type": "text", "text": f"Collected acknowledgement decision '{decision}' for call '{call_id}'."}],
        "ack": {"call_id": call_id, "decision": decision},
    }


async def voip_did_route_upsert(args: Json) -> Json:
    state = _state_gate("voip.did_route.upsert")
    if state:
        return state
    gate = _write_gate("voip.did_route.upsert")
    if gate:
        return gate
    did_e164 = _normalize_did(str(args.get("did_e164", "")))
    persona_id = str(args.get("persona_id", "")).strip()
    if not did_e164 or not persona_id:
        return _text("Please provide 'did_e164' and 'persona_id'.")
    if APP_DID and did_e164 != APP_DID:
        return _text(
            f"Single-DID policy active. Only '{APP_DID}' can be mapped in this app instance."
        )
    allow_source_cidrs_raw = args.get("allow_source_cidrs") or []
    allow_source_cidrs = [str(v).strip() for v in allow_source_cidrs_raw if str(v).strip()]
    route: RouteRecord = {
        "did_e164": did_e164,
        "persona_id": persona_id,
        "project_id": str(args.get("project_id", "")).strip() or None,
        "allow_source_cidrs": allow_source_cidrs,
        "enabled": bool(args.get("enabled", True)),
    }
    _DID_ROUTES[did_e164] = route
    return _text(
        f"DID route upserted for {did_e164} -> persona='{persona_id}' "
        f"(cidrs={len(allow_source_cidrs)}, enabled={route['enabled']})."
    )


async def voip_did_route_get(args: Json) -> Json:
    state = _state_gate("voip.did_route.get")
    if state:
        return state
    did_e164 = _normalize_did(str(args.get("did_e164", "")))
    if not did_e164:
        return _text("Please provide 'did_e164'.")
    route = _DID_ROUTES.get(did_e164)
    if not route:
        return _text(f"No route found for DID '{did_e164}'.")
    return {
        "content": [{"type": "text", "text": "DID route loaded."}],
        "route": route,
    }


async def voip_did_route_delete(args: Json) -> Json:
    state = _state_gate("voip.did_route.delete")
    if state:
        return state
    gate = _write_gate("voip.did_route.delete")
    if gate:
        return gate
    did_e164 = _normalize_did(str(args.get("did_e164", "")))
    if not did_e164:
        return _text("Please provide 'did_e164'.")
    existed = _DID_ROUTES.pop(did_e164, None) is not None
    return _text(f"DID route delete for '{did_e164}': {'deleted' if existed else 'not_found'}.")


async def voip_ingress_route_call(args: Json) -> Json:
    state = _state_gate("voip.ingress.route_call")
    if state:
        return state
    gate = _telephony_gate("voip.ingress.route_call")
    if gate:
        return gate
    did_e164 = _normalize_did(str(args.get("to_did_e164", "")))
    source_ip = str(args.get("source_ip", "")).strip()
    from_number = str(args.get("from_number", "")).strip()
    provider_call_id = str(args.get("provider_call_id", "")).strip()
    if not did_e164 or not source_ip or not provider_call_id:
        return _text("Please provide 'to_did_e164', 'source_ip', and 'provider_call_id'.")
    if APP_DID and did_e164 != APP_DID:
        return {
            "content": [{"type": "text", "text": f"Inbound DID '{did_e164}' rejected by single-DID policy."}],
            "decision": "reject_did_policy",
            "provider": TELEPHONY_PROVIDER,
        }
    route = _DID_ROUTES.get(did_e164)
    if not route:
        return {
            "content": [{"type": "text", "text": f"No DID route for '{did_e164}'."}],
            "decision": "reject_no_route",
            "provider": TELEPHONY_PROVIDER,
        }
    if not bool(route.get("enabled", True)):
        return {
            "content": [{"type": "text", "text": f"Route for '{did_e164}' is disabled."}],
            "decision": "reject_route_disabled",
            "provider": TELEPHONY_PROVIDER,
        }
    allow_source_cidrs = [str(v) for v in route.get("allow_source_cidrs", [])]
    if not _source_ip_allowed(source_ip, allow_source_cidrs):
        _audit({"action": "ingress_route_call", "decision": "reject_source_ip", "did_e164": did_e164, "source_ip": source_ip})
        return {
            "content": [{"type": "text", "text": "Source IP rejected by allowlist policy."}],
            "decision": "reject_source_ip",
            "provider": TELEPHONY_PROVIDER,
            "route": route,
        }
    persona_id = str(route["persona_id"])
    pseudo_session_id = f"did-{did_e164}-{provider_call_id}"
    _audit({"action": "ingress_route_call", "decision": "accept", "did_e164": did_e164, "persona_id": persona_id, "source_ip": source_ip})
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Ingress accepted for DID '{did_e164}'. "
                    f"Route -> persona '{persona_id}'."
                ),
            }
        ],
        "decision": "accept",
        "provider": TELEPHONY_PROVIDER,
        "persona_id": persona_id,
        "provider_call_id": provider_call_id,
        "from_number": from_number,
        "session": {
            "entry_mode": "call",
            "session_id": pseudo_session_id,
            "resume_token": f"resume-{provider_call_id}",
        },
        "route": route,
    }


async def voip_webhook_verify(args: Json) -> Json:
    """Verify a provider webhook signature. Twilio uses HMAC-SHA1 over the
    URL + sorted form params (base64 in ``X-Twilio-Signature``); Telnyx
    uses ed25519 with a timestamp header; Infobip ships its own scheme.
    This tool supports the two HMAC variants by ``algorithm`` — pure
    providers can ship their own verify tool and share the audit hook.

    Always returns a structured ``verified`` flag rather than raising,
    so the orchestrator can log rejects without exception-handling noise.
    """
    state = _state_gate("voip.webhook.verify")
    if state:
        return state
    algorithm = str(args.get("algorithm", "sha1")).strip().lower()
    payload = str(args.get("payload", ""))
    expected = str(args.get("signature", "")).strip()
    secret = str(args.get("secret", "")).strip() or WEBHOOK_SECRET
    if not secret:
        return {
            "content": [{"type": "text", "text": "No webhook secret configured; verification skipped."}],
            "verified": False,
            "reason": "no_secret",
        }
    if not expected:
        return {
            "content": [{"type": "text", "text": "Missing signature header."}],
            "verified": False,
            "reason": "missing_signature",
        }
    digestmod = hashlib.sha1 if algorithm == "sha1" else hashlib.sha256
    computed = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), digestmod).hexdigest()
    # Constant-time compare; accept either hex or hex-with-prefix ("sha256=…").
    compare = expected.split("=", 1)[1] if "=" in expected else expected
    verified = hmac.compare_digest(computed, compare.lower())
    _audit({"action": "webhook_verify", "channel": "voip", "algorithm": algorithm, "verified": verified})
    return {
        "content": [{"type": "text", "text": f"Webhook verify: {'ok' if verified else 'failed'}."}],
        "verified": verified,
        "algorithm": algorithm,
    }


async def voip_incident_trigger(args: Json) -> Json:
    """Raise an incident → persona escalation. The persona's policy
    decides whether to call, WhatsApp, or Telegram; this tool just
    records the trigger + emits an audit event. Recurrent checks
    (battery low, camera offline, door left open) all funnel here
    so the orchestrator stays a single switch statement.
    """
    state = _state_gate("voip.incident.trigger")
    if state:
        return state
    policy = _policy_gate("voip.incident.trigger", args)
    if policy:
        return policy
    incident_id = str(args.get("incident_id", "")).strip()
    severity = str(args.get("severity", "info")).strip().lower()
    reason = str(args.get("reason", "")).strip()
    persona_id = str(args.get("persona_id", "")).strip()
    if not incident_id or not reason:
        return _text("Please provide 'incident_id' and 'reason'.")
    if severity not in {"info", "warn", "critical"}:
        severity = "info"
    _audit({
        "action": "incident_trigger",
        "channel": "voip",
        "incident_id": incident_id,
        "severity": severity,
        "reason": reason[:200],
        "persona_id": persona_id,
    })
    return {
        "content": [{"type": "text", "text": f"Incident '{incident_id}' ({severity}) recorded."}],
        "incident": {
            "incident_id": incident_id,
            "severity": severity,
            "reason": reason,
            "persona_id": persona_id,
        },
    }


async def voip_server_status(_: Json) -> Json:
    return {
        "content": [{"type": "text", "text": f"Server install_state={INSTALL_STATE}"}],
        "server": {
            "channel": "voip",
            "install_state": INSTALL_STATE,
            "telephony_enabled": TELEPHONY_ENABLED,
            "telephony_provider": TELEPHONY_PROVIDER,
            "write_enabled": WRITE_ENABLED,
            "dry_run": DRY_RUN,
            "audit_events": len(_AUDIT_EVENTS),
        },
    }


async def voip_audit_list(args: Json) -> Json:
    limit = max(1, min(int(args.get("limit", 20) or 20), 200))
    return {
        "content": [{"type": "text", "text": f"Returning {min(limit, len(_AUDIT_EVENTS))} audit events."}],
        "events": _AUDIT_EVENTS[-limit:],
    }


TOOLS: List[ToolDef] = [
    ToolDef(
        name="hp.voip.call.create",
        description="Create an outbound call. Write-gated.",
        input_schema={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Destination E.164 number"},
                "from": {"type": "string", "description": "Optional source DID"},
                "prompt": {"type": "string", "description": "Optional initial message"},
                "persona_id": {"type": "string", "description": "Persona performing the action"},
                "consent_granted": {"type": "boolean", "default": False},
                "idempotency_key": {"type": "string", "description": "Optional dedupe key for retries"},
                "metadata": {"type": "object", "additionalProperties": True},
            },
            "required": ["to"],
        },
        handler=voip_create_outbound_call,
    ),
    ToolDef(
        name="hp.voip.call.status",
        description="Get current status of a call.",
        input_schema={
            "type": "object",
            "properties": {
                "call_id": {"type": "string"},
                "persona_id": {"type": "string"},
            },
            "required": ["call_id"],
        },
        handler=voip_get_call_status,
    ),
    ToolDef(
        name="hp.voip.call.end",
        description="End an in-progress call. Write-gated.",
        input_schema={
            "type": "object",
            "properties": {
                "call_id": {"type": "string"},
            },
            "required": ["call_id"],
        },
        handler=voip_end_call,
    ),
    ToolDef(
        name="hp.voip.call.play_tts",
        description="Play TTS text on a live call. Write-gated.",
        input_schema={
            "type": "object",
            "properties": {
                "call_id": {"type": "string"},
                "text": {"type": "string"},
                "persona_id": {"type": "string"},
            },
            "required": ["call_id", "text"],
        },
        handler=voip_play_tts,
    ),
    ToolDef(
        name="hp.voip.call.collect_ack",
        description="Collect DTMF or voice acknowledgement from an active call.",
        input_schema={
            "type": "object",
            "properties": {
                "call_id": {"type": "string"},
                "signal": {"type": "string", "description": "1/2/3 or ack/snooze/escalate"},
            },
            "required": ["call_id"],
        },
        handler=voip_collect_ack,
    ),
    ToolDef(
        name="hp.voip.did_route.upsert",
        description="Create/update DID -> persona route with optional source CIDR allowlist. Write-gated.",
        input_schema={
            "type": "object",
            "properties": {
                "did_e164": {"type": "string"},
                "persona_id": {"type": "string"},
                "project_id": {"type": "string"},
                "allow_source_cidrs": {"type": "array", "items": {"type": "string"}},
                "enabled": {"type": "boolean", "default": True},
            },
            "required": ["did_e164", "persona_id"],
        },
        handler=voip_did_route_upsert,
    ),
    ToolDef(
        name="hp.voip.did_route.get",
        description="Get DID route by E.164 number.",
        input_schema={
            "type": "object",
            "properties": {
                "did_e164": {"type": "string"},
            },
            "required": ["did_e164"],
        },
        handler=voip_did_route_get,
    ),
    ToolDef(
        name="hp.voip.did_route.delete",
        description="Delete DID route by E.164 number. Write-gated.",
        input_schema={
            "type": "object",
            "properties": {
                "did_e164": {"type": "string"},
            },
            "required": ["did_e164"],
        },
        handler=voip_did_route_delete,
    ),
    ToolDef(
        name="hp.voip.ingress.route_call",
        description="Route inbound provider call (DID + source IP) to persona. Requires TELEPHONY_ENABLED=true.",
        input_schema={
            "type": "object",
            "properties": {
                "to_did_e164": {"type": "string"},
                "from_number": {"type": "string"},
                "source_ip": {"type": "string"},
                "provider_call_id": {"type": "string"},
            },
            "required": ["to_did_e164", "source_ip", "provider_call_id"],
        },
        handler=voip_ingress_route_call,
    ),
    ToolDef(
        name="hp.voip.webhook.verify",
        description="Verify a provider webhook signature (HMAC-SHA1 / SHA256). Returns verified=bool.",
        input_schema={
            "type": "object",
            "properties": {
                "algorithm": {"type": "string", "enum": ["sha1", "sha256"], "default": "sha1"},
                "payload": {"type": "string", "description": "Exact bytes the provider signed"},
                "signature": {"type": "string", "description": "Provider-sent signature header value"},
                "secret": {"type": "string", "description": "Override of VOIP_WEBHOOK_SECRET"},
            },
            "required": ["payload", "signature"],
        },
        handler=voip_webhook_verify,
    ),
    ToolDef(
        name="hp.voip.incident.trigger",
        description="Record an incident for persona-led escalation. Orchestrator decides channel (VoIP/WhatsApp/Telegram).",
        input_schema={
            "type": "object",
            "properties": {
                "incident_id": {"type": "string"},
                "severity": {"type": "string", "enum": ["info", "warn", "critical"], "default": "info"},
                "reason": {"type": "string"},
                "persona_id": {"type": "string"},
            },
            "required": ["incident_id", "reason"],
        },
        handler=voip_incident_trigger,
    ),
    ToolDef(
        name="hp.voip.server.status",
        description="Return install state and server safety mode.",
        input_schema={"type": "object", "properties": {}},
        handler=voip_server_status,
    ),
    ToolDef(
        name="hp.voip.audit.list",
        description="List recent immutable-style audit entries for this server process.",
        input_schema={
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 200}},
        },
        handler=voip_audit_list,
    ),
]

app = create_mcp_app(server_name="homepilot-voip", tools=TOOLS)
