"""
Ingress bridge — map an ``hp.voip.ingress.route_call`` decision to a
HomePilot voice-call session.

The VoIP MCP server (``agentic/integrations/mcp/voip``) exposes a
``hp.voip.ingress.route_call`` tool that takes a provider callback
(to_did_e164, from_number, source_ip, provider_call_id) and returns
either ``{"decision": "accept", "persona_id": "...", ...}`` or a
reject verdict.

This bridge closes the last gap: given an accept decision, create the
matching ``voice_call`` session so the persona picks up the phone
with the same WebSocket lifecycle a browser caller would use. Reject
verdicts short-circuit without touching ``voice_call`` at all.

Design constraints
------------------

1. **Additive.** No existing ``voice_call`` callers change. This module
   is new code; it imports ``service.create_session`` and produces the
   same dict shape the REST router produces — so downstream (WS resume,
   barge-in, streaming, persona_call) works unchanged.
2. **Non-destructive.** Gated behind ``TELEPHONY_ENABLED=true``. Off by
   default; flipping it on introduces a NEW ingress path without
   modifying the browser path. Off → behaviour identical to today.
3. **Small.** ~70 LoC of glue, no new tables, no new endpoints. A
   future ``telephony/router.py`` will expose HTTP webhooks that call
   this bridge; today the bridge stands on its own for unit tests and
   for the MCP-driven orchestration path.

The bridge does NOT sign or verify provider webhooks — that lives in
``hp.voip.webhook.verify`` on the MCP side. By the time a decision
reaches this module, authenticity has already been established.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from . import service, store
from .config import VoiceCallConfig
from .policy import PolicyError


logger = logging.getLogger("voice_call.ingress_bridge")


class IngressBridgeError(Exception):
    """Raised when a bridge call can't be fulfilled. Caller should map
    to an HTTP 4xx/5xx in whatever adapter it sits behind."""

    def __init__(self, code: str, detail: str, http_status: int = 400) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.http_status = http_status


def telephony_enabled() -> bool:
    """Read the feature flag at call-time (not import-time) so tests +
    runtime env flips take effect without a process restart."""
    return os.getenv("TELEPHONY_ENABLED", "false").lower() == "true"


def open_session_from_decision(
    *,
    decision: Dict[str, Any],
    cfg: VoiceCallConfig,
    user_id: str,
    client_platform: Optional[str] = "pstn",
    app_version: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a voice-call session from a VoIP MCP ingress decision.

    ``decision`` is the JSON returned by ``hp.voip.ingress.route_call``.
    Only the ``accept`` branch creates a session; every other branch
    raises ``IngressBridgeError`` with a stable code so the caller can
    produce provider-friendly responses (e.g. Twilio ``<Reject/>``).

    Raises
    ------
    IngressBridgeError
        - ``telephony_disabled``      flag off; safe to fall through to chat
        - ``ingress_not_accepted``    decision != 'accept'
        - ``missing_persona``         accept decision lacks persona_id
        - ``session_create_failed``   voice_call.service raised
    """
    if not telephony_enabled():
        raise IngressBridgeError(
            "telephony_disabled",
            "TELEPHONY_ENABLED=false; ingress bridge is inert.",
            http_status=503,
        )

    verdict = str(decision.get("decision", "")).strip().lower()
    if verdict != "accept":
        raise IngressBridgeError(
            "ingress_not_accepted",
            f"VoIP ingress returned decision='{verdict}'.",
            http_status=403,
        )

    persona_id = str(decision.get("persona_id", "")).strip() or None
    if not persona_id:
        raise IngressBridgeError(
            "missing_persona",
            "Accept decision missing 'persona_id'.",
        )

    # Optional conversation pinning — not all routes carry one. When
    # absent, voice_call creates a fresh conversation like any other
    # first-call-from-this-caller would.
    conversation_id = None
    route = decision.get("route") or {}
    if isinstance(route, dict):
        conversation_id = (route.get("conversation_id") or route.get("project_id") or None)
        if conversation_id is not None:
            conversation_id = str(conversation_id).strip() or None

    try:
        row = service.create_session(
            user_id=user_id,
            conversation_id=conversation_id,
            persona_id=persona_id,
            entry_mode="call",
            client_platform=client_platform,
            app_version=app_version,
            cfg=cfg,
        )
    except PolicyError as exc:
        logger.warning(
            "[ingress] create_session policy_error user=%s persona=%s code=%s",
            user_id, persona_id, exc.code,
        )
        raise IngressBridgeError(
            "session_create_failed",
            f"{exc.code}: {exc.detail}",
            http_status=exc.http_status,
        ) from exc

    # Audit-style event on the voice_call event log so the ingress path
    # is visible in the existing observability pipeline alongside
    # browser-originated sessions.
    provider_call_id = str(decision.get("provider_call_id", "")).strip() or None
    from_number = str(decision.get("from_number", "")).strip() or None
    store.append_event(
        session_id=row["id"],
        seq=1,
        event_type="ingress.accepted",
        payload={
            "provider": str(decision.get("provider", "")).strip() or "unknown",
            "provider_call_id": provider_call_id,
            "from_number": from_number,
        },
    )
    logger.info(
        "[ingress] accept user=%s sid=%s persona=%s provider_call=%s",
        user_id, row["id"], persona_id, provider_call_id,
    )
    return row
