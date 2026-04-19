"""
Typed errors for the interactive service.

Every error carries a stable ``code`` so the router can map it to
the right HTTP status without leaking internal details, and so the
frontend can branch on the code string instead of parsing messages.

Design rule: the service NEVER raises raw ``Exception``. Unexpected
exceptions are caught at the router boundary and wrapped in
``InteractiveError(code='internal', …)`` so observability stays
tidy. See ``router.py`` handlers.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class InteractiveError(Exception):
    """Base — all interactive-service errors inherit from this."""

    #: Default HTTP status when the router maps this to a response.
    http_status: int = 500
    #: Stable machine-readable code. Frontend branches on this.
    code: str = "internal"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        http_status: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        self.data = dict(data or {})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": False,
            "code": self.code,
            "error": self.message,
            "data": self.data,
        }


# ── Configuration / feature-flag ──────────────────────────────────

class ServiceDisabledError(InteractiveError):
    http_status = 503
    code = "service_disabled"


# ── Input validation ──────────────────────────────────────────────

class InvalidInputError(InteractiveError):
    http_status = 400
    code = "invalid_input"


# ── Authorization ─────────────────────────────────────────────────

class NotAuthenticatedError(InteractiveError):
    http_status = 401
    code = "not_authenticated"


class NotAuthorizedError(InteractiveError):
    """Authenticated but the resource doesn't belong to the caller."""

    http_status = 404  # probe-safe — 404 hides existence
    code = "not_found"


# ── Resource lookup ───────────────────────────────────────────────

class NotFoundError(InteractiveError):
    http_status = 404
    code = "not_found"


# ── Structural / graph ────────────────────────────────────────────

class GraphError(InteractiveError):
    http_status = 422
    code = "graph_invalid"


class CapacityError(InteractiveError):
    """Branching graph or similar structure exceeds configured cap."""

    http_status = 422
    code = "capacity_exceeded"


# ── Policy ────────────────────────────────────────────────────────

class PolicyBlockError(InteractiveError):
    http_status = 403
    code = "policy_blocked"


class ConsentRequiredError(InteractiveError):
    http_status = 403
    code = "consent_required"


# ── Runtime ───────────────────────────────────────────────────────

class InvalidStateError(InteractiveError):
    http_status = 409
    code = "invalid_state"


class CooldownError(InteractiveError):
    http_status = 429
    code = "cooldown"
