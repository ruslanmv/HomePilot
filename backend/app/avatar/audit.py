"""
Avatar Studio — audit logging for enterprise traceability.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("avatar")


def audit_event(event: str, **kwargs: object) -> None:
    """Log a structured audit event."""
    logger.info("avatar_event=%s %s", event, kwargs)
